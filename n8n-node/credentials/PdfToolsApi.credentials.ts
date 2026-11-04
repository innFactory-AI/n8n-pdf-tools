import type {
	IAuthenticateGeneric,
	Icon,
	ICredentialTestRequest,
	ICredentialType,
	INodeProperties,
} from 'n8n-workflow';

export class PdfToolsApi implements ICredentialType {
	name = 'pdfToolsApi';

	displayName = 'PDF Tools API';

	icon: Icon = {
		light: 'file:../nodes/PdfTools/pdfTools.svg',
		dark: 'file:../nodes/PdfTools/pdfTools.dark.svg',
	};

	documentationUrl = 'https://github.com/innFactory-AI/n8n-pdf-tools#readme';

	properties: INodeProperties[] = [
		{
			displayName: 'Base URL',
			name: 'baseUrl',
			type: 'string',
			default: 'http://n8n-pdf-tools:8080',
			description:
				'URL of the n8n-pdf-tools service. In the same Kubernetes namespace as n8n the service name is enough.',
		},
		{
			displayName: 'API Token',
			name: 'apiToken',
			type: 'string',
			typeOptions: { password: true },
			default: '',
			description: 'Only needed if the service runs with API_TOKEN set',
		},
	];

	authenticate: IAuthenticateGeneric = {
		type: 'generic',
		properties: {
			headers: {
				'X-API-Key': '={{$credentials.apiToken}}',
			},
		},
	};

	test: ICredentialTestRequest = {
		request: {
			baseURL: '={{$credentials.baseUrl}}',
			url: '/v1/ping',
			method: 'GET',
		},
	};
}
