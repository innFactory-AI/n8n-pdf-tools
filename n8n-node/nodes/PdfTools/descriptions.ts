import type { INodeProperties, INodePropertyOptions } from 'n8n-workflow';

/** Operations that produce several files (one output item per file by default). */
export const FILE_OPERATIONS = ['split', 'render', 'images'];
/** Operations that return JSON instead of a file. */
export const JSON_OPERATIONS = ['info', 'text', 'formFields'];
/** Operations that combine several input files into one. */
export const COMBINE_OPERATIONS = ['merge', 'imagesToPdf'];

export const operations: INodePropertyOptions[] = [
	{
		name: 'Add Page Numbers',
		value: 'pageNumbers',
		action: 'Add page numbers',
		description: 'Number pages, e.g. "Seite {page} von {total}"',
	},
	{
		name: 'Add Watermark',
		value: 'watermark',
		action: 'Add a text watermark',
		description: 'Text watermark or stamp on pages',
	},
	{
		name: 'Compress',
		value: 'compress',
		action: 'Compress a PDF',
		description: 'Lossless, or lossy with image recompression',
	},
	{ name: 'Decrypt', value: 'decrypt', action: 'Remove the password from a PDF' },
	{ name: 'Delete Pages', value: 'delete', action: 'Delete pages' },
	{
		name: 'Encrypt',
		value: 'encrypt',
		action: 'Password protect a PDF',
		description: 'AES-256 with optional permissions',
	},
	{ name: 'Extract Images', value: 'images', action: 'Extract embedded images' },
	{
		name: 'Extract Text',
		value: 'text',
		action: 'Extract text',
		description: 'Text (and optionally tables) per page',
	},
	{ name: 'Fill Form', value: 'fillForm', action: 'Fill form fields' },
	{ name: 'Flatten Form', value: 'flatten', action: 'Flatten form fields and annotations' },
	{ name: 'Get Form Fields', value: 'formFields', action: 'List form fields' },
	{
		name: 'Get Info',
		value: 'info',
		action: 'Get PDF info',
		description: 'Page count, sizes, metadata, bookmarks, form fields',
	},
	{ name: 'Images to PDF', value: 'imagesToPdf', action: 'Convert images to a PDF' },
	{ name: 'Insert Blank Pages', value: 'insertBlank', action: 'Insert blank pages' },
	{ name: 'Merge', value: 'merge', action: 'Merge PDFs' },
	{
		name: 'Overlay / Letterhead',
		value: 'overlay',
		action: 'Add a letterhead or overlay',
		description: 'Place pages of another PDF under or over the pages',
	},
	{ name: 'Render Pages', value: 'render', action: 'Render pages to images' },
	{ name: 'Repair', value: 'repair', action: 'Repair a damaged PDF' },
	{ name: 'Rotate Pages', value: 'rotate', action: 'Rotate pages' },
	{ name: 'Run Pipeline', value: 'pipeline', action: 'Run several operations in one call' },
	{ name: 'Select / Reorder Pages', value: 'select', action: 'Keep or reorder pages' },
	{ name: 'Set Metadata', value: 'metadata', action: 'Set PDF metadata' },
	{ name: 'Split', value: 'split', action: 'Split a PDF' },
	{
		name: 'Stamp Image',
		value: 'stampImage',
		action: 'Stamp an image onto pages',
		description: 'Logo, signature, seal',
	},
];

const show = (...operation: string[]) => ({ show: { operation } });
const hide = (...operation: string[]) => ({ hide: { operation } });
// inside collections, display options must point to the root parameter ('/operation')
const showRoot = (...operation: string[]) => ({ show: { '/operation': operation } });
const hideRoot = (...operation: string[]) => ({ hide: { '/operation': operation } });

const PAGES_HINT =
	'1-based: 1-3,5,7-, last, 5-last, odd, even, all. Descending ranges reverse (last-1).';

const positionOptions: INodePropertyOptions[] = [
	'top-left',
	'top-center',
	'top-right',
	'center-left',
	'center',
	'center-right',
	'bottom-left',
	'bottom-center',
	'bottom-right',
].map((value) => ({
	name: value.replace(/(^|-)(\w)/g, (_m, dash, c) => (dash ? ' ' : '') + c.toUpperCase()),
	value,
}));

const layerOption: INodeProperties = {
	displayName: 'Layer',
	name: 'layer',
	type: 'options',
	options: [
		{ name: 'Over Content', value: 'over' },
		{ name: 'Under Content', value: 'under' },
	],
	default: 'over',
};

const pagesOption = (
	description = `Pages to apply to (default all). ${PAGES_HINT}`,
): INodeProperties => ({
	displayName: 'Pages',
	name: 'pages',
	type: 'string',
	default: '',
	placeholder: 'all',
	description,
});

export const properties: INodeProperties[] = [
	{
		displayName: 'Authentication',
		name: 'authentication',
		type: 'options',
		noDataExpression: true,
		options: [
			{
				name: 'None (In-Cluster)',
				value: 'none',
				description: 'Call the service by its cluster URL without a token',
			},
			{
				name: 'PDF Tools API Credential',
				value: 'pdfToolsApi',
				description: 'Use a credential with URL and token, e.g. when the service has API_TOKEN set',
			},
		],
		default: 'none',
	},
	{
		displayName: 'Service URL',
		name: 'serviceUrl',
		type: 'string',
		default: 'http://n8n-pdf-tools:8080',
		displayOptions: { show: { authentication: ['none'] } },
		description:
			'URL of n8n-pdf-tools. In the same namespace as n8n the service name is enough; otherwise use http://n8n-pdf-tools.NAMESPACE.svc.cluster.local:8080.',
	},
	{
		displayName: 'Operation',
		name: 'operation',
		type: 'options',
		noDataExpression: true,
		options: operations,
		default: 'split',
	},

	// ------------------------------------------------------------ input
	{
		displayName: 'Input Binary Field',
		name: 'binaryPropertyName',
		type: 'string',
		default: 'data',
		required: true,
		displayOptions: hide('merge', 'imagesToPdf'),
		description: 'Name of the binary field that holds the PDF',
	},
	{
		displayName: 'Combine',
		name: 'combineMode',
		type: 'options',
		displayOptions: show('merge', 'imagesToPdf'),
		options: [
			{
				name: 'All Input Items',
				value: 'items',
				description: 'One file per item, in item order; outputs one item',
			},
			{
				name: 'Fields of Each Item',
				value: 'fields',
				description: 'Several binary fields of the same item; outputs one item per input item',
			},
		],
		default: 'items',
	},
	{
		displayName: 'Input Binary Field',
		name: 'combineBinaryPropertyName',
		type: 'string',
		default: 'data',
		required: true,
		displayOptions: { show: { operation: ['merge', 'imagesToPdf'], combineMode: ['items'] } },
		description: 'Binary field to take from every item',
	},
	{
		displayName: 'Input Binary Fields',
		name: 'combineBinaryPropertyNames',
		type: 'string',
		default: 'data_0, data_1',
		required: true,
		displayOptions: { show: { operation: ['merge', 'imagesToPdf'], combineMode: ['fields'] } },
		description: 'Comma-separated binary fields, in order',
	},

	// ------------------------------------------------------------ pages
	{
		displayName: 'Pages',
		name: 'pages',
		type: 'string',
		default: '',
		required: true,
		placeholder: '3,1,2',
		displayOptions: show('select', 'delete'),
		description: 'Pages to keep (in this order) or delete. ,.',
	},
	{
		displayName: 'Angle',
		name: 'angle',
		type: 'options',
		displayOptions: show('rotate'),
		options: [
			{ name: '90° Clockwise', value: 90 },
			{ name: '180°', value: 180 },
			{ name: '90° Counter-Clockwise', value: 270 },
		],
		default: 90,
	},
	{
		...pagesOption(),
		displayOptions: show('rotate'),
	},
	{
		displayName: 'After Pages',
		name: 'after',
		type: 'string',
		default: '0',
		required: true,
		displayOptions: show('insertBlank'),
		description: 'Insert after these pages; 0 = before the first page. Example: 0,2,last.',
	},
	{
		displayName: 'Count',
		name: 'count',
		type: 'number',
		typeOptions: { minValue: 1, maxValue: 100 },
		default: 1,
		displayOptions: show('insertBlank'),
		description: 'Blank pages per position',
	},

	// ------------------------------------------------------------ split
	{
		displayName: 'Split By',
		name: 'splitMode',
		type: 'options',
		displayOptions: show('split'),
		options: [
			{ name: 'Page Ranges', value: 'ranges', description: 'One file per range' },
			{ name: 'Every N Pages', value: 'every' },
			{ name: 'Bookmarks', value: 'bookmarks', description: 'One file per top-level bookmark' },
		],
		default: 'every',
	},
	{
		displayName: 'Ranges',
		name: 'ranges',
		type: 'string',
		default: '',
		required: true,
		placeholder: '1-2,3,4-',
		displayOptions: { show: { operation: ['split'], splitMode: ['ranges'] } },
		description: 'One output file per comma-separated token. ,.',
	},
	{
		displayName: 'Pages per File',
		name: 'every',
		type: 'number',
		typeOptions: { minValue: 1 },
		default: 1,
		displayOptions: { show: { operation: ['split'], splitMode: ['every'] } },
	},

	// ------------------------------------------------------------ content
	{
		displayName: 'Text',
		name: 'text',
		type: 'string',
		typeOptions: { rows: 2 },
		default: '',
		required: true,
		placeholder: 'VERTRAULICH',
		displayOptions: show('watermark'),
		description: 'Watermark text; line breaks allowed',
	},
	{
		displayName: 'Format',
		name: 'format',
		type: 'string',
		default: '{page} / {total}',
		displayOptions: show('pageNumbers'),
		description: 'Placeholders: {page} and {total}',
	},
	{
		displayName: 'Image Binary Field',
		name: 'imageBinaryPropertyName',
		type: 'string',
		default: 'image',
		required: true,
		displayOptions: show('stampImage'),
		description: 'Binary field with the PNG/JPEG to stamp (same item)',
	},
	{
		displayName: 'Overlay Binary Field',
		name: 'overlayBinaryPropertyName',
		type: 'string',
		default: 'letterhead',
		required: true,
		displayOptions: show('overlay'),
		description:
			'Binary field with the overlay PDF (same item). Page k goes on page k; its last page repeats (1 page = everywhere, 2 pages = first page + follow-up pages).',
	},
	{
		displayName: 'Layer',
		name: 'overlayLayer',
		type: 'options',
		displayOptions: show('overlay'),
		options: [
			{ name: 'Under Content (Letterhead)', value: 'under' },
			{ name: 'Over Content', value: 'over' },
		],
		default: 'under',
	},

	// ------------------------------------------------------------ forms
	{
		displayName: 'Values',
		name: 'formInput',
		type: 'options',
		displayOptions: show('fillForm'),
		options: [
			{ name: 'Define Below', value: 'fields' },
			{ name: 'JSON', value: 'json' },
		],
		default: 'fields',
	},
	{
		displayName: 'Fields',
		name: 'formFields',
		type: 'fixedCollection',
		typeOptions: { multipleValues: true },
		placeholder: 'Add Field',
		default: {},
		displayOptions: { show: { operation: ['fillForm'], formInput: ['fields'] } },
		options: [
			{
				displayName: 'Field',
				name: 'field',
				values: [
					{
						displayName: 'Name',
						name: 'name',
						type: 'string',
						default: '',
						description: 'Field name as listed by "Get Form Fields"',
					},
					{
						displayName: 'Value',
						name: 'value',
						type: 'string',
						default: '',
						description: 'Checkboxes: true/false or a state name',
					},
				],
			},
		],
	},
	{
		displayName: 'Values (JSON)',
		name: 'formJson',
		type: 'json',
		default: '{\n  "Name": "Max Mustermann",\n  "Agree": true\n}',
		displayOptions: { show: { operation: ['fillForm'], formInput: ['json'] } },
	},
	{
		displayName: 'Flatten After Filling',
		name: 'flatten',
		type: 'boolean',
		default: false,
		displayOptions: show('fillForm'),
		description: 'Whether to burn the values into the pages so they can no longer be edited',
	},

	// ------------------------------------------------------------ metadata / security
	{
		displayName: 'Metadata',
		name: 'metadata',
		type: 'collection',
		placeholder: 'Add Field',
		default: {},
		displayOptions: show('metadata'),
		options: ['title', 'author', 'subject', 'keywords', 'creator', 'producer'].map((key) => ({
			displayName: key.charAt(0).toUpperCase() + key.slice(1),
			name: key,
			type: 'string' as const,
			default: '',
		})),
	},
	{
		displayName: 'Remove Keys',
		name: 'removeKeys',
		type: 'multiOptions',
		displayOptions: show('metadata'),
		options: ['title', 'author', 'subject', 'keywords', 'creator', 'producer'].map((key) => ({
			name: key.charAt(0).toUpperCase() + key.slice(1),
			value: key,
		})),
		default: [],
	},
	{
		displayName: 'Clear Existing Metadata',
		name: 'clear',
		type: 'boolean',
		default: false,
		displayOptions: show('metadata'),
		description: 'Whether to remove all existing metadata first',
	},
	{
		displayName: 'Open Password',
		name: 'userPassword',
		type: 'string',
		typeOptions: { password: true },
		default: '',
		displayOptions: show('encrypt'),
		description: 'Needed to open the PDF; leave empty to only restrict permissions',
	},
	{
		displayName: 'Owner Password',
		name: 'ownerPassword',
		type: 'string',
		typeOptions: { password: true },
		default: '',
		displayOptions: show('encrypt'),
		description: 'Needed to change permissions; defaults to the open password',
	},
	{
		displayName: 'Allow',
		name: 'permissions',
		type: 'multiOptions',
		displayOptions: show('encrypt'),
		options: [
			{ name: 'Annotate', value: 'annotate' },
			{ name: 'Copy Text', value: 'copy' },
			{ name: 'Fill Forms', value: 'forms' },
			{ name: 'Modify', value: 'modify' },
			{ name: 'Print', value: 'print' },
		],
		default: ['annotate', 'copy', 'forms', 'modify', 'print'],
	},

	// ------------------------------------------------------------ pipeline
	{
		displayName: 'Operations (JSON)',
		name: 'ops',
		type: 'json',
		default:
			'[\n  {"op": "delete", "pages": "1"},\n  {"op": "page_numbers", "format": "{page} / {total}"},\n  {"op": "compress"}\n]',
		displayOptions: show('pipeline'),
		description:
			'Array of operations, see the n8n-pdf-tools README. Ops that return files or JSON (split, render, text, info, images, form_fields) must come last.',
	},
	{
		displayName: 'Assets',
		name: 'assets',
		type: 'fixedCollection',
		typeOptions: { multipleValues: true },
		placeholder: 'Add Asset',
		default: {},
		displayOptions: show('pipeline'),
		description:
			'Extra files from the same item that ops reference by name (merge, overlay, stamp_image)',
		options: [
			{
				displayName: 'Asset',
				name: 'asset',
				values: [
					{
						displayName: 'Name',
						name: 'name',
						type: 'string',
						default: '',
						placeholder: 'letterhead.pdf',
						description: 'Name used in the ops, e.g. {"op": "overlay", "file": "letterhead.pdf"}',
					},
					{ displayName: 'Binary Field', name: 'binaryPropertyName', type: 'string', default: '' },
				],
			},
		],
	},

	// ------------------------------------------------------------ options
	{
		displayName: 'Options',
		name: 'options',
		type: 'collection',
		placeholder: 'Add Option',
		default: {},
		options: [
			{
				displayName: 'Color',
				name: 'color',
				type: 'color',
				default: '#888888',
				displayOptions: showRoot('watermark', 'pageNumbers'),
			},
			{
				displayName: 'Dpi',
				name: 'dpi',
				type: 'number',
				typeOptions: { minValue: 10, maxValue: 300 },
				default: 150,
				displayOptions: showRoot('render'),
			},
			{
				displayName: 'Font Size',
				name: 'fontSize',
				type: 'number',
				typeOptions: { minValue: 1 },
				default: 48,
				displayOptions: showRoot('watermark', 'pageNumbers'),
				description: 'Default 48 for watermarks, 10 for page numbers',
			},
			{
				displayName: 'Ignore Unknown Fields',
				name: 'ignoreUnknown',
				type: 'boolean',
				default: false,
				displayOptions: showRoot('fillForm'),
				description: 'Whether to skip values for fields the form does not have instead of failing',
			},
			{
				displayName: 'Image Format',
				name: 'imageFormat',
				type: 'options',
				options: [
					{ name: 'PNG', value: 'png' },
					{ name: 'JPEG', value: 'jpg' },
					{ name: 'WebP', value: 'webp' },
				],
				default: 'png',
				displayOptions: showRoot('render'),
			},
			{
				displayName: 'Image Quality',
				name: 'imageQuality',
				type: 'number',
				typeOptions: { minValue: 10, maxValue: 95 },
				default: 75,
				displayOptions: showRoot('compress', 'render'),
				description:
					'Compress: recompress images as JPEG with this quality (lossy). Render: JPEG/WebP quality.',
			},
			{
				displayName: 'Include Tables',
				name: 'tables',
				type: 'boolean',
				default: false,
				displayOptions: showRoot('text'),
				description: 'Whether to also extract tables as row arrays',
			},
			{
				displayName: 'Keep Layout',
				name: 'layout',
				type: 'boolean',
				default: false,
				displayOptions: showRoot('text'),
				description: 'Whether to keep the visual layout with spaces',
			},
			{ ...layerOption, displayOptions: showRoot('watermark', 'stampImage') },
			{
				displayName: 'Linearize',
				name: 'linearize',
				type: 'boolean',
				default: false,
				displayOptions: showRoot('compress'),
				description: 'Whether to optimize for fast web view',
			},
			{
				displayName: 'Margin (Mm)',
				name: 'marginMm',
				type: 'number',
				default: 10,
				displayOptions: showRoot('watermark', 'pageNumbers', 'stampImage', 'imagesToPdf'),
			},
			{
				displayName: 'Max Image Size (Px)',
				name: 'maxImagePx',
				type: 'number',
				typeOptions: { minValue: 64 },
				default: 2000,
				displayOptions: showRoot('compress'),
				description: 'Downscale images to this long side',
			},
			{
				displayName: 'Min Image Size (Px)',
				name: 'minSize',
				type: 'number',
				default: 32,
				displayOptions: showRoot('images'),
				description: 'Skip images smaller than this',
			},
			{
				displayName: 'Opacity',
				name: 'opacity',
				type: 'number',
				typeOptions: { minValue: 0, maxValue: 1, numberPrecision: 2 },
				default: 0.3,
				displayOptions: showRoot('watermark', 'stampImage'),
				description: 'Default 0.3 for watermarks, 1 for images',
			},
			{
				displayName: 'Output File Name',
				name: 'fileName',
				type: 'string',
				default: '',
				displayOptions: hideRoot(...JSON_OPERATIONS, ...FILE_OPERATIONS),
				description: 'File name of the result; default is derived from the input',
			},
			{
				displayName: 'Page Size',
				name: 'pageSize',
				type: 'options',
				options: [
					{ name: 'A4', value: 'a4' },
					{ name: 'A4 Landscape', value: 'a4-landscape' },
					{ name: 'Image Size', value: '' },
					{ name: 'Letter', value: 'letter' },
					{ name: 'Letter Landscape', value: 'letter-landscape' },
				],
				default: '',
				displayOptions: showRoot('imagesToPdf'),
			},
			{
				...pagesOption(),
				displayOptions: showRoot(
					'watermark',
					'pageNumbers',
					'stampImage',
					'overlay',
					'text',
					'render',
					'images',
				),
			},
			{
				displayName: 'Password',
				name: 'password',
				type: 'string',
				typeOptions: { password: true },
				default: '',
				displayOptions: hideRoot('merge', 'imagesToPdf'),
				description: 'Password of an encrypted input PDF',
			},
			{
				displayName: 'Position',
				name: 'position',
				type: 'options',
				options: positionOptions,
				default: 'center',
				displayOptions: showRoot('watermark', 'pageNumbers', 'stampImage'),
				description:
					'Default center for watermarks, bottom center for page numbers, bottom right for images',
			},
			{
				displayName: 'Put Output File in Field',
				name: 'outputBinaryPropertyName',
				type: 'string',
				default: 'data',
				displayOptions: hideRoot(...JSON_OPERATIONS),
				description: 'Binary field for the result',
			},
			{
				displayName: 'Rotation (Degrees)',
				name: 'rotation',
				type: 'number',
				default: 45,
				displayOptions: showRoot('watermark'),
			},
			{
				displayName: 'Split Into Items',
				name: 'splitIntoItems',
				type: 'boolean',
				default: true,
				displayOptions: showRoot(...FILE_OPERATIONS, 'pipeline'),
				description:
					'Whether to output one item per file. If off, all files go into one item as data_0, data_1, … (using the output field name as prefix).',
			},
			{
				displayName: 'Start Number',
				name: 'start',
				type: 'number',
				default: 1,
				displayOptions: showRoot('pageNumbers'),
			},
			{
				displayName: 'Width (Mm)',
				name: 'widthMm',
				type: 'number',
				typeOptions: { minValue: 1 },
				default: 40,
				displayOptions: showRoot('stampImage'),
			},
		],
	},
];
