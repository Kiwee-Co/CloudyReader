// @ts-check
import { existsSync } from 'node:fs';
import starlight from '@astrojs/starlight';
import { defineConfig } from 'astro/config';

const repo = 'https://github.com/Kiwee-Co/CloudyReader';

// While the manual is written, CR_PENDING=1 builds without the sidebar pages and style sheets
// that do not exist yet. Without it, a missing page or style sheet fails the build.
const pending = process.env.CR_PENDING === '1';
const exists = (/** @type {string} */ path) => existsSync(new URL(path, import.meta.url));
const page = (/** @type {string} */ slug) =>
	['md', 'mdx'].some((ext) => exists(`./src/content/docs/${slug}.${ext}`));
const pages = (/** @type {string[]} */ ...slugs) => (pending ? slugs.filter(page) : slugs);
const styles = (/** @type {string[]} */ ...files) => (pending ? files.filter(exists) : files);

export default defineConfig({
	site: 'https://cloudyreader.com',
	// Old addresses of pages that moved or merged. The custom-domain runbook left the site for
	// site/MAINTAINING.md.
	redirects: {
		'/custom-domain/': '/developer/contributing/',
		'/developer/custom-domain/': '/developer/contributing/',
		'/manual/using-the-app/': '/manual/reference/window/',
		'/manual/voices/': '/manual/reference/voices/',
		'/manual/pronunciation/': '/manual/reference/pronunciation-examples/',
		'/manual/offline-and-privacy/': '/about/privacy/',
		'/manual/settings-and-cli/': '/manual/reference/command-line/',
		'/manual/': '/manual/getting-started/',
		'/about/': '/about/project/',
		'/developer/': '/developer/building/',
	},
	integrations: [
		starlight({
			title: 'Cloudy Reader',
			description: 'Reads National Science Bowl questions aloud on your Mac.',
			logo: { src: './src/assets/logo.svg' },
			favicon: '/favicon.svg',
			social: [{ icon: 'github', label: 'Source code on GitHub', href: repo }],
			editLink: { baseUrl: `${repo}/edit/main/site/` },
			// The docs route renders src/content/docs/404.md as /404.html. Starlight's own 404 route
			// would render the same page again and warn about the conflict.
			disable404Route: true,
			sidebar: [
				{
					label: 'Start here',
					items: pages('manual/getting-started', 'download', 'manual/first-week'),
				},
				{ label: 'Tutorials', items: [{ autogenerate: { directory: 'manual/tutorials' } }] },
				{ label: 'Tasks', items: [{ autogenerate: { directory: 'manual/tasks' } }] },
				{ label: 'Reference', items: [{ autogenerate: { directory: 'manual/reference' } }] },
				{ label: 'Concepts', items: [{ autogenerate: { directory: 'manual/concepts' } }] },
				{
					label: 'Help',
					items: pages('manual/troubleshooting', 'manual/faq', 'manual/get-help'),
				},
				{ label: 'About', items: [{ autogenerate: { directory: 'about' } }] },
				{
					label: 'Developer',
					collapsed: true,
					items: [{ autogenerate: { directory: 'developer' } }],
				},
			],
			customCss: styles(
				'./src/styles/custom.css',
				'./src/styles/figures.css',
				'./src/styles/print.css',
			),
			components: { Footer: './src/components/Footer.astro' },
		}),
	],
});
