// Generate the LLM surface into the site output, following the llmstxt.org v2
// spec (https://llmstxt.org):
//
//   llms.txt         — the curated index in spec-v2 format: H1 name, blockquote
//                      summary, details paragraphs, H2 "file list" sections
//                      with `[name](url): notes` links, and an "Optional"
//                      section for secondary links agents can skip.
//   llms-full.txt    — every page's markdown concatenated, for agents that
//                      want the whole site in one fetch.
//   <page>.html.md   — a clean markdown variant of every page at the SAME URL
//                      as the rendered page with `.md` appended (spec v2's
//                      page.html.md convention): an agent on
//                      /security-model.html fetches
//                      /security-model.html.md and gets clean markdown.
//
// Discovery (spec v2): every rendered HTML page gets
//   <link rel="describedby" href="…/llms.txt"> and
//   <link rel="alternate" type="text/markdown" href="…/page.html.md">
// injected into its <head> via VitePress's transformHead hook (see
// .vitepress/config.mts).
import { readFileSync, writeFileSync, existsSync, mkdirSync, readdirSync } from 'node:fs'
import { join, dirname, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const SITE_DIR = dirname(fileURLToPath(import.meta.url))
const DIST = join(SITE_DIR, 'dist')
const REPO_RAW = 'https://raw.githubusercontent.com/hybridindie/comfyui_mcp/main/docs/site/'
const SITE_URL = 'https://hybridindie.github.io/comfyui_mcp/'

const TITLE = 'comfyui-mcp-secure'
const SUMMARY =
  'A secure MCP server for ComfyUI — generate images, run workflows, and manage ' +
  'models from any AI agent. 53 tools across generation, jobs, discovery, files, ' +
  'models, and custom nodes, with workflow inspection, path sanitization, rate ' +
  'limiting, and structured audit logging built in.'
const DETAILS =
  'comfyui-mcp-secure is a security-first MCP server built on FastMCP 4: every ' +
  'tool call is rate-limited and audit-logged, file operations pass through a ' +
  'path sanitizer, and every workflow submission goes through the inspector ' +
  '(audit mode logs warnings; enforce mode blocks unapproved nodes and elicits ' +
  'the user). Start with what-why (the reasoning), concepts (the vocabulary), ' +
  'and getting-started for setup. Every page below also serves a clean markdown ' +
  'variant at its URL with `.md` appended (e.g. `security-model.html.md`), plus ' +
  '`llms-full.txt` for the whole site in one fetch.'

// section -> ordered source paths (relative to docs/site/). `optional: true`
// marks the spec's "Optional" section (secondary links agents can skip when a
// shorter context is needed).
const SECTIONS = [
  { name: 'Home', sources: ['index.md', 'what-why.md', 'concepts.md'] },
  {
    name: 'Getting started',
    sources: [
      'getting-started.md',
      'getting-started-install.md',
      'getting-started-configure.md',
      'getting-started-clients.md',
      'getting-started-first-session.md',
    ],
  },
  {
    name: 'Security',
    sources: [
      'security-model.md',
      'security-audit-mode.md',
      'security-enforce-mode.md',
      'security-audit-log.md',
      'security-threat-model.md',
      'security-blocked-endpoints.md',
    ],
  },
  {
    name: 'Architecture',
    sources: [
      'architecture/index.md',
      'architecture/server.md',
      'architecture/client.md',
      'architecture/workflow-pipeline.md',
      'architecture/resources-prompts.md',
      'architecture/tasks.md',
    ],
  },
  {
    name: 'Reference',
    sources: [
      'reference.md',
      'reference-tools.md',
      'reference-resources-prompts.md',
      'reference-config.md',
      'reference-env-vars.md',
      'reference-server-features.md',
      'reference-errors.md',
    ],
  },
  {
    name: 'Guides',
    sources: [
      'guides.md',
      'guides-generate.md',
      'guides-custom-workflows.md',
      'guides-manage-models.md',
      'guides-production.md',
      'guides-docker.md',
    ],
  },
  { name: 'Optional', sources: ['changelog.md'], optional: true },
]

// Source path -> the site URL VitePress actually serves. VitePress's default
// (cleanUrls not enabled) renders foo.md -> foo.html and subdir/index.md ->
// subdir/ — trailing-slash URLs 404, so every link must be the .html form.
function htmlPath(srcRel) {
  const noExt = srcRel.replace(/\.md$/, '')
  if (noExt === 'index') return SITE_URL
  if (noExt.endsWith('/index')) return SITE_URL + noExt.slice(0, -'/index'.length) + '/'
  return SITE_URL + noExt + '.html'
}

// The .md-variant URL per spec v2 (page.html.md; index pages use index.html.md).
function mdVariantUrl(srcRel) {
  const html = htmlPath(srcRel)
  return html.endsWith('/') ? html + 'index.html.md' : html + '.md'
}

// dist-relative path for the variant file, mirroring the page's location.
function mdVariantDistPath(srcRel) {
  const rel = srcRel.replace(/\.md$/, '')
  return join(DIST, rel === 'index' ? 'index.html.md' : rel + '.html.md')
}

function loadBody(srcRel) {
  const abs = join(SITE_DIR, srcRel)
  if (!existsSync(abs)) return null
  return readFileSync(abs, 'utf8').replace(/^---\n.*?\n---\n/s, '').trim()
}

function pageTitle(body, srcRel) {
  const m = body.match(/^# (.+)$/m)
  return m ? m[1] : srcRel.replace(/\.md$/, '')
}

mkdirSync(DIST, { recursive: true })
const writtenMd = new Set()

// --- llms.txt (spec v2) + llms-full.txt ---
const index = [`# ${TITLE}`, '', `> ${SUMMARY}`, '', DETAILS, '']
const full = [`# ${TITLE}`, '', `> ${SUMMARY}`, '', DETAILS, '']

for (const section of SECTIONS) {
  index.push(`## ${section.name}`)
  full.push(`## ${section.name}`, '')
  for (const srcRel of section.sources) {
    const body = loadBody(srcRel)
    if (body == null) continue
    const pageUrl = htmlPath(srcRel)
    const mdUrl = mdVariantUrl(srcRel)
    const rawUrl = REPO_RAW + srcRel
    const title = pageTitle(body, srcRel)
    const note =
      section.optional
        ? `: release history — [markdown](${mdUrl}) · [raw source](${rawUrl})`
        : `: [markdown](${mdUrl}) · [raw source](${rawUrl})`
    index.push(`- [${title}](${pageUrl})${note}`)
    full.push(body + '\n')
    // page.html.md variant at the page's own URL (spec v2)
    const variantPath = mdVariantDistPath(srcRel)
    mkdirSync(dirname(variantPath), { recursive: true })
    writeFileSync(variantPath, body + '\n')
    writtenMd.add(variantPath)
  }
  index.push('')
  full.push('')
}

// Optional footer per spec: where the machine-readable contract lives.
index.push(
  '## Optional',
  '',
  `- [README (source of truth)](https://github.com/hybridindie/comfyui_mcp/blob/main/README.md): the full tool tables and configuration reference`,
  `- [Security rules](https://github.com/hybridindie/comfyui_mcp/blob/main/.opencode/rules/security.md): the non-negotiable security invariants as enforced by tests`,
  `- [Raw markdown sources](${REPO_RAW}): every page above, fetchable without the site`,
  '',
)
writeFileSync(join(DIST, 'llms.txt'), index.join('\n') + '\n')
writeFileSync(join(DIST, 'llms-full.txt'), full.join('\n') + '\n')

// Copy the variants for any stray pages not in SECTIONS (safety net) — skip
// assets/dist. Walk the site root's source markdown.
function walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name.startsWith('.') || entry.name === 'node_modules' || entry.name === 'dist') continue
    const rel = join(dir, entry.name)
    if (entry.isDirectory()) walk(rel)
    else if (entry.name.endsWith('.md')) {
      const srcRel = relative(SITE_DIR, rel).split('\\').join('/')
      if (writtenMd.has(join(DIST, mdVariantDistPath(srcRel)))) continue
      const body = loadBody(srcRel)
      if (body == null) continue
      const variantPath = mdVariantDistPath(srcRel)
      mkdirSync(dirname(variantPath), { recursive: true })
      writeFileSync(variantPath, body + '\n')
    }
  }
}
walk(SITE_DIR)

console.log('generated llms.txt + llms-full.txt + page.html.md variants')