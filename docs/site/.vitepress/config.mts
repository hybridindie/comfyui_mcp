import { defineConfig } from 'vitepress'
import { withMermaid } from 'vitepress-plugin-mermaid'

const BASE = '/comfyui_mcp/'

export default withMermaid(defineConfig({
  lang: 'en-US',
  title: 'comfyui-mcp-secure',
  description:
    'A secure MCP server for ComfyUI — generate images, run workflows, and manage models from any AI agent. Workflow inspection, path sanitization, rate limiting, and audit logging built in.',
  base: BASE,
  outDir: 'dist',
  ignoreDeadLinks: false,
  head: [
    ['link', { rel: 'icon', type: 'image/svg+xml', href: BASE + 'logo.svg' }],
  ],
  transformHead: ({ pageData }) => {
    const base = BASE.replace(/\/$/, '')
    const describedby = base + '/llms.txt'
    // Per-page markdown variant URL (llmstxt.org v2 page.html.md form),
    // matching the file llms-gen.mjs writes.
    const rel = (pageData.relativePath ?? 'index.md').replace(/\.md$/, '')
    const variant = base + '/' + rel + '.html.md'
    return [
      ['link', { rel: 'describedby', type: 'text/markdown', href: describedby }],
      ['link', { rel: 'alternate', type: 'text/markdown', href: variant }],
    ]
  },
  mermaid: {
    // plugin auto-switches to theme 'dark' when VitePress dark mode is active
    securityLevel: 'loose',
    startOnLoad: false,
  },
  mermaidPlugin: {
    class: 'mermaid-blocks',
  },
  themeConfig: {
    siteTitle: 'comfyui-mcp-secure',
    nav: [
      { text: 'Guide', link: '/what-why' },
      { text: 'Getting Started', link: '/getting-started-install' },
      { text: 'Security', link: '/security-model' },
      { text: 'Reference', link: '/reference-tools' },
      {
        text: 'LLM',
        items: [
          { text: 'llms.txt (index)', link: BASE + 'llms.txt' },
          { text: 'llms-full.txt (one doc)', link: BASE + 'llms-full.txt' },
        ],
      },
      {
        text: 'GitHub',
        link: 'https://github.com/hybridindie/comfyui_mcp'
      }
    ],
    sidebar: [
      {
        text: 'Start Here',
        items: [
          { text: 'What & why', link: '/what-why' },
          { text: 'Core concepts', link: '/concepts' },
          { text: 'How it compares', link: '/comparison' }
        ]
      },
      {
        text: 'Getting Started',
        items: [
          { text: 'Overview', link: '/getting-started' },
          { text: 'Install the server', link: '/getting-started-install' },
          { text: 'Configure', link: '/getting-started-configure' },
          { text: 'Add to your MCP client', link: '/getting-started-clients' },
          { text: 'First session', link: '/getting-started-first-session' }
        ]
      },
      {
        text: 'Security',
        items: [
          { text: 'The security model', link: '/security-model' },
          { text: 'Audit mode', link: '/security-audit-mode' },
          { text: 'Enforce mode & elicitation', link: '/security-enforce-mode' },
          { text: 'The audit log', link: '/security-audit-log' },
          { text: 'Threat model', link: '/security-threat-model' },
          { text: 'Blocked endpoints', link: '/security-blocked-endpoints' }
        ]
      },
      {
        text: 'Architecture',
        items: [
          { text: 'Overview', link: '/architecture/' },
          { text: 'Server & middleware', link: '/architecture/server' },
          { text: 'Client & transport', link: '/architecture/client' },
          { text: 'Workflow pipeline', link: '/architecture/workflow-pipeline' },
          { text: 'Resources & prompts', link: '/architecture/resources-prompts' },
          { text: 'Background tasks', link: '/architecture/tasks' }
        ]
      },
      {
        text: 'Reference',
        items: [
          { text: 'Overview', link: '/reference' },
          { text: 'Tools', link: '/reference-tools' },
          { text: 'Resources & prompts', link: '/reference-resources-prompts' },
          { text: 'Configuration', link: '/reference-config' },
          { text: 'Environment variables', link: '/reference-env-vars' },
          { text: 'Server capability flags', link: '/reference-server-features' },
          { text: 'Errors & recovery', link: '/reference-errors' },
          { text: 'Changelog', link: '/changelog' }
        ]
      },
      {
        text: 'Guides',
        items: [
          { text: 'Generate images', link: '/guides-generate' },
          { text: 'Work with custom workflows', link: '/guides-custom-workflows' },
          { text: 'Manage models', link: '/guides-manage-models' },
          { text: 'Run securely in production', link: '/guides-production' },
          { text: 'Docker deployment', link: '/guides-docker' }
        ]
      }
    ],
    search: {
      provider: 'local',
      options: {
        translations: {
          button: { buttonText: 'Search docs' }
        }
      }
    },
    socialLinks: [
      { icon: 'github', link: 'https://github.com/hybridindie/comfyui_mcp' }
    ],
    editLink: {
      pattern:
        'https://github.com/hybridindie/comfyui_mcp/edit/main/docs/site/:path',
      text: 'Edit this page on GitHub'
    },
    footer: {
      message: '53 tools · 5 resources · 4 prompts · MIT Licensed',
      copyright: 'MIT Licensed. Copyright © 2026 hybridindie'
    }
  },
}))