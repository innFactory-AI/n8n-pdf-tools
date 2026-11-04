import type {
	IBinaryData,
	IDataObject,
	IExecuteFunctions,
	IHttpRequestOptions,
	INodeExecutionData,
	INodeType,
	INodeTypeDescription,
	JsonObject,
} from 'n8n-workflow';
import { NodeApiError, NodeConnectionTypes, NodeOperationError } from 'n8n-workflow';

import { COMBINE_OPERATIONS, FILE_OPERATIONS, properties } from './descriptions';

interface ApiFile {
	name: string;
	mime_type: string;
	size: number;
	data: string;
}

interface Upload {
	data: Buffer;
	fileName: string;
	mimeType: string;
}

const PERMISSIONS = ['print', 'copy', 'modify', 'annotate', 'forms'];

/** Drop options the user did not set so the API defaults apply. */
function compact(values: IDataObject): IDataObject {
	return Object.fromEntries(
		Object.entries(values).filter(([, v]) => v !== undefined && v !== '' && v !== null),
	);
}

/** Map node parameters to n8n-pdf-tools pipeline operations. */
async function buildOps(
	this: IExecuteFunctions,
	operation: string,
	i: number,
	options: IDataObject,
	assets: Record<string, Upload>,
	upload: (itemIndex: number, field: string) => Promise<Upload>,
): Promise<IDataObject[]> {
	const param = (name: string, fallback?: unknown) => this.getNodeParameter(name, i, fallback);
	const pick = (mapping: Record<string, string>) =>
		compact(Object.fromEntries(Object.entries(mapping).map(([api, opt]) => [api, options[opt]])));
	const style = () =>
		pick({
			pages: 'pages',
			font_size: 'fontSize',
			color: 'color',
			opacity: 'opacity',
			position: 'position',
			margin_mm: 'marginMm',
			layer: 'layer',
		});

	switch (operation) {
		case 'info':
			return [{ op: 'info' }];
		case 'formFields':
			return [{ op: 'form_fields' }];
		case 'text':
			return [{ op: 'text', ...pick({ pages: 'pages', layout: 'layout', tables: 'tables' }) }];
		case 'render':
			return [
				{
					op: 'render',
					...pick({ pages: 'pages', dpi: 'dpi', format: 'imageFormat', quality: 'imageQuality' }),
				},
			];
		case 'images':
			return [{ op: 'images', ...pick({ pages: 'pages', min_size: 'minSize' }) }];
		case 'split': {
			const mode = param('splitMode') as string;
			if (mode === 'ranges') return [{ op: 'split', ranges: param('ranges') }];
			if (mode === 'bookmarks') return [{ op: 'split', by: 'bookmarks' }];
			return [{ op: 'split', every: param('every') }];
		}
		case 'select':
		case 'delete':
			return [{ op: operation, pages: param('pages') }];
		case 'rotate':
			return [
				{
					op: 'rotate',
					angle: param('angle'),
					...compact({ pages: param('pages', '') as string }),
				},
			];
		case 'insertBlank':
			return [{ op: 'insert_blank', after: String(param('after')), count: param('count') }];
		case 'watermark':
			return [
				{ op: 'watermark', text: param('text'), ...style(), ...pick({ rotation: 'rotation' }) },
			];
		case 'pageNumbers':
			return [
				{ op: 'page_numbers', format: param('format'), ...style(), ...pick({ start: 'start' }) },
			];
		case 'stampImage':
			assets['stamp'] = await upload(i, param('imageBinaryPropertyName') as string);
			return [{ op: 'stamp_image', file: 'stamp', ...style(), ...pick({ width_mm: 'widthMm' }) }];
		case 'overlay':
			assets['overlay'] = await upload(i, param('overlayBinaryPropertyName') as string);
			return [
				{
					op: 'overlay',
					file: 'overlay',
					layer: param('overlayLayer'),
					...pick({ pages: 'pages' }),
				},
			];
		case 'fillForm': {
			let values: IDataObject;
			if (param('formInput') === 'json') {
				const raw = param('formJson');
				values = (typeof raw === 'string' ? JSON.parse(raw) : raw) as IDataObject;
			} else {
				const rows = ((param('formFields', {}) as IDataObject).field ?? []) as IDataObject[];
				values = Object.fromEntries(rows.map((r) => [String(r.name), r.value]));
			}
			return [
				{
					op: 'fill_form',
					values,
					flatten: param('flatten'),
					ignore_unknown: options.ignoreUnknown === true,
				},
			];
		}
		case 'flatten':
			return [{ op: 'flatten' }];
		case 'metadata': {
			const op: IDataObject = {
				op: 'metadata',
				clear: param('clear'),
				...compact(param('metadata', {}) as IDataObject),
			};
			for (const key of param('removeKeys', []) as string[]) op[key] = null;
			return [op];
		}
		case 'compress':
			return [
				{
					op: 'compress',
					...pick({
						image_quality: 'imageQuality',
						max_image_px: 'maxImagePx',
						linearize: 'linearize',
					}),
				},
			];
		case 'encrypt': {
			const allowed = param('permissions', PERMISSIONS) as string[];
			return [
				{
					op: 'encrypt',
					user_password: param('userPassword'),
					owner_password: param('ownerPassword'),
					...Object.fromEntries(PERMISSIONS.map((p) => [`allow_${p}`, allowed.includes(p)])),
				},
			];
		}
		case 'decrypt':
		case 'repair':
			return [{ op: 'decrypt' }];
		case 'pipeline': {
			const raw = param('ops');
			const ops = (typeof raw === 'string' ? JSON.parse(raw) : raw) as IDataObject[];
			if (!Array.isArray(ops)) {
				throw new NodeOperationError(this.getNode(), 'Operations must be a JSON array', {
					itemIndex: i,
				});
			}
			const rows = ((param('assets', {}) as IDataObject).asset ?? []) as IDataObject[];
			for (const row of rows) {
				assets[String(row.name)] = await upload(i, String(row.binaryPropertyName));
			}
			return ops;
		}
	}
	throw new NodeOperationError(this.getNode(), `Unknown operation "${operation}"`, {
		itemIndex: i,
	});
}

export class PdfTools implements INodeType {
	description: INodeTypeDescription = {
		displayName: 'PDF Tools',
		name: 'pdfTools',
		icon: { light: 'file:pdfTools.svg', dark: 'file:pdfTools.dark.svg' },
		group: ['transform'],
		version: [1],
		subtitle: '={{$parameter["operation"]}}',
		description:
			'Split, merge, watermark, number, stamp, fill, extract and protect PDFs with n8n-pdf-tools',
		defaults: { name: 'PDF Tools' },
		usableAsTool: true,
		inputs: [NodeConnectionTypes.Main],
		outputs: [NodeConnectionTypes.Main],
		credentials: [{ name: 'pdfToolsApi', required: true }],
		properties,
	};

	async execute(this: IExecuteFunctions): Promise<INodeExecutionData[][]> {
		const items = this.getInputData();
		const operation = this.getNodeParameter('operation', 0) as string;
		const credentials = await this.getCredentials('pdfToolsApi');
		const baseUrl = String(credentials.baseUrl).replace(/\/+$/, '');
		const returnData: INodeExecutionData[] = [];
		const node = this.getNode();

		const upload = async (itemIndex: number, field: string): Promise<Upload> => {
			const meta: IBinaryData = this.helpers.assertBinaryData(itemIndex, field);
			return {
				data: await this.helpers.getBinaryDataBuffer(itemIndex, field),
				fileName: meta.fileName ?? `${field}.${meta.fileExtension ?? 'bin'}`,
				mimeType: meta.mimeType,
			};
		};

		const call = async (
			itemIndex: number,
			path: string,
			form: FormData,
			binaryResponse = false,
		): Promise<{ data?: IDataObject; buffer?: Buffer }> => {
			const request: IHttpRequestOptions = {
				method: 'POST',
				url: `${baseUrl}${path}`,
				body: form,
				returnFullResponse: true,
				ignoreHttpStatusErrors: true,
				timeout: 300_000,
			};
			if (binaryResponse) request.encoding = 'arraybuffer';
			const response = (await this.helpers.httpRequestWithAuthentication.call(
				this,
				'pdfToolsApi',
				request,
			)) as { statusCode: number; body: unknown };
			let body = response.body;
			if (response.statusCode >= 400) {
				if (Buffer.isBuffer(body) || body instanceof ArrayBuffer) {
					try {
						body = JSON.parse(Buffer.from(body as Buffer).toString('utf8'));
					} catch {
						body = { message: Buffer.from(body as Buffer).toString('utf8') };
					}
				}
				const error = (body ?? {}) as IDataObject;
				throw new NodeApiError(this.getNode(), error as JsonObject, {
					itemIndex,
					httpCode: String(response.statusCode),
					message: String(error.message ?? `HTTP ${response.statusCode}`),
					description: error.error ? `Error code: ${String(error.error)}` : undefined,
				});
			}
			if (binaryResponse) return { buffer: Buffer.from(body as ArrayBuffer) };
			return { data: (typeof body === 'string' ? JSON.parse(body) : body) as IDataObject };
		};

		const blob = (file: Upload) => new Blob([new Uint8Array(file.data)], { type: file.mimeType });

		const toBinary = async (file: ApiFile, fileName?: string) =>
			await this.helpers.prepareBinaryData(
				Buffer.from(file.data, 'base64'),
				fileName || file.name,
				file.mime_type,
			);

		/** Turn the API result into output items. */
		const emit = async (
			itemIndex: number | number[],
			result: IDataObject,
			options: IDataObject,
			source?: INodeExecutionData,
		) => {
			const pairedItem = Array.isArray(itemIndex)
				? itemIndex.map((item) => ({ item }))
				: { item: itemIndex };
			const outField = String(options.outputBinaryPropertyName || 'data');
			if (!Array.isArray(result.files)) {
				// JSON result (info, text, form fields): keep the input's binary data
				returnData.push({ json: result, binary: source?.binary, pairedItem });
				return;
			}
			const files = result.files as ApiFile[];
			const multi = FILE_OPERATIONS.includes(operation) || operation === 'pipeline';
			if (files.length === 0) {
				// e.g. no embedded images: keep the flow going with one item that says so
				returnData.push({ json: { count: 0 }, pairedItem });
				return;
			}
			if (!multi || files.length === 1) {
				const binary = await toBinary(files[0], options.fileName as string | undefined);
				returnData.push({
					json: multi ? { fileName: files[0].name, index: 0, count: 1 } : (source?.json ?? {}),
					binary: { ...(multi ? {} : (source?.binary ?? {})), [outField]: binary },
					pairedItem,
				});
				return;
			}
			if (options.splitIntoItems === false) {
				const binary: Record<string, IBinaryData> = {};
				for (const [index, file] of files.entries()) {
					binary[`${outField}_${index}`] = await toBinary(file);
				}
				returnData.push({
					json: { count: files.length, fileNames: files.map((f) => f.name) },
					binary,
					pairedItem,
				});
				return;
			}
			for (const [index, file] of files.entries()) {
				returnData.push({
					json: { fileName: file.name, index, count: files.length },
					binary: { [outField]: await toBinary(file) },
					pairedItem,
				});
			}
		};

		// ---------------------------------------------------------------- combine all items
		if (
			COMBINE_OPERATIONS.includes(operation) &&
			this.getNodeParameter('combineMode', 0) === 'items'
		) {
			try {
				const field = this.getNodeParameter('combineBinaryPropertyName', 0) as string;
				const options = this.getNodeParameter('options', 0, {}) as IDataObject;
				const files: Upload[] = [];
				for (let i = 0; i < items.length; i++) files.push(await upload(i, field));
				const result = await combine(operation, files, options);
				await emit(
					items.map((_, i) => i),
					result,
					options,
				);
			} catch (error) {
				if (!this.continueOnFail()) {
					throw new NodeOperationError(this.getNode(), error as Error, {
						description: (error as NodeApiError).description ?? undefined,
					});
				}
				returnData.push({ json: { error: (error as Error).message }, pairedItem: { item: 0 } });
			}
			return [returnData];
		}

		async function combine(op: string, files: Upload[], options: IDataObject) {
			if (op === 'merge') {
				if (files.length < 2) throw new NodeOperationError(node, 'Merge needs at least two PDFs');
				const form = new FormData();
				form.append('file', blob(files[0]), files[0].fileName);
				const names = files.slice(1).map((_, k) => `#${k + 1}.pdf`);
				files.slice(1).forEach((f, k) => form.append('assets', blob(f), names[k]));
				form.append('ops', JSON.stringify([{ op: 'merge', files: names }]));
				form.append('output', 'json');
				return (await call(0, '/v1/pipeline', form)).data as IDataObject;
			}
			const form = new FormData();
			for (const f of files) form.append('files', blob(f), f.fileName);
			if (options.pageSize) form.append('page_size', String(options.pageSize));
			if (options.marginMm !== undefined) form.append('margin_mm', String(options.marginMm));
			const { buffer } = await call(0, '/v1/images-to-pdf', form, true);
			const stem = files[0].fileName.replace(/\.[^.]+$/, '') || 'images';
			return {
				files: [
					{
						name: `${stem}.pdf`,
						mime_type: 'application/pdf',
						size: buffer!.length,
						data: buffer!.toString('base64'),
					},
				],
			};
		}

		// ---------------------------------------------------------------- per item
		for (let i = 0; i < items.length; i++) {
			try {
				const options = this.getNodeParameter('options', i, {}) as IDataObject;

				if (COMBINE_OPERATIONS.includes(operation)) {
					const fields = (this.getNodeParameter('combineBinaryPropertyNames', i) as string)
						.split(',')
						.map((f) => f.trim())
						.filter(Boolean);
					const files: Upload[] = [];
					for (const field of fields) files.push(await upload(i, field));
					await emit(i, await combine(operation, files, options), options, items[i]);
					continue;
				}

				const input = await upload(i, this.getNodeParameter('binaryPropertyName', i) as string);
				const assets: Record<string, Upload> = {};
				const ops = buildOps.call(this, operation, i, options, assets, upload);

				const form = new FormData();
				form.append('file', blob(input), input.fileName);
				form.append('ops', JSON.stringify(await ops));
				form.append('output', 'json');
				if (options.password) form.append('password', String(options.password));
				for (const [name, asset] of Object.entries(assets)) {
					form.append('assets', blob(asset), name);
				}
				const { data } = await call(i, '/v1/pipeline', form);
				await emit(i, data as IDataObject, options, items[i]);
			} catch (error) {
				if (this.continueOnFail()) {
					returnData.push({ json: { error: (error as Error).message }, pairedItem: { item: i } });
					continue;
				}
				throw new NodeOperationError(this.getNode(), error as Error, {
					itemIndex: i,
					description: (error as NodeApiError).description ?? undefined,
				});
			}
		}

		return [returnData];
	}
}
