// @ts-check
import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';

const repo = 'https://github.com/Kiwee-Co/CloudyReader';

export default defineConfig({
	site: 'https://cloudyreader.com',
	// The page moved into the Developer folder; the old address keeps working.
	redirects: { '/custom-domain/': '/developer/custom-domain/' },
	integrations: [
		starlight({
			title: 'Cloudy Reader',
			description: 'Reads National Science Bowl questions aloud on your Mac.',
			logo: { src: './src/assets/logo.svg' },
			favicon: '/favicon.svg',
			social: [{ icon: 'github', label: 'Source code on GitHub', href: repo }],
			editLink: { baseUrl: `${repo}/edit/main/site/` },
			sidebar: [
				{ label: 'Manual', items: [{ autogenerate: { directory: 'manual' } }] },
				{ label: 'Developer', items: [{ autogenerate: { directory: 'developer' } }] },
			],
			customCss: ['./src/styles/custom.css'],
			components: { Footer: './src/components/Footer.astro' },
		}),
	],
});
