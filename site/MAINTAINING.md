# Maintaining cloudyreader.com

This file is for maintainers of the documentation site. The site does not publish it. The manual
itself lives in `site/src/content/docs/`; how to edit it is in the Contribute page of the manual
(`site/src/content/docs/developer/contributing.mdx`).

## How the site is built and published

The site is an Astro Starlight project in `site/`. The workflow `.github/workflows/pages.yml`
builds it and publishes it to GitHub Pages:

- It runs on a push to `main` that changes `site/`, `scripts/check_site.py`, or the workflow, and
  on a manual run (**Actions > Pages > Run workflow**).
- It installs the locked packages (`npm ci`), builds (`npm run build`), checks the built site with
  `python3 scripts/check_site.py site/dist`, and deploys `site/dist`.
- **Settings > Pages > Build and deployment > Source** must be **GitHub Actions**, as the comment
  at the top of `pages.yml` says.

To build and check the site on your Mac, use Node.js at the version in `site/.node-version`:

```bash
cd site
npm ci
npm run build
python3 ../scripts/check_site.py dist
```

`site/.npmrc` pins the public npm registry and turns off install scripts. If your own `~/.npmrc`
points npm at another registry, run npm with `NPM_CONFIG_USERCONFIG=/dev/null`, so only
`site/.npmrc` applies.

While pages are still being written, `CR_PENDING=1 npm run build` builds without the sidebar pages
and style sheets that do not exist yet. Without the variable, a missing page fails the build, so
the published site never has a dead sidebar link.

## Where the site settings live

| What                                       | Where                                                       |
| ------------------------------------------ | ----------------------------------------------------------- |
| Sidebar groups and order                   | `sidebar` in `site/astro.config.mjs`                        |
| Redirects from old page addresses          | `redirects` in `site/astro.config.mjs`                      |
| Colors and the key style                   | `site/src/styles/custom.css`                                |
| Print layout and the one-page cheat sheets | `site/src/styles/print.css`                                 |
| Footer links and the version line          | `site/src/components/Footer.astro` (the `version` constant) |
| Overrides of Starlight's interface strings | `site/src/content/i18n/en.json` (empty: the defaults apply) |

Change the footer's `version` only after the manual is checked against that release.

## Search

The search box uses Pagefind, which indexes the pages at build time. `pagefind.ranking.termFrequency`
in `site/astro.config.mjs` is 0.5 instead of Starlight's 0.1, so a page that keeps naming a message,
such as "No voice is installed.", ranks above a page that names it once.

The search test (check G8 of the manual plan) runs 20 queries. It passes when the expected page is
among the first three results for at least 18 of them. The result on 2026-11-05 was 20 of 20.

| Query                 | Expected page in the first three                                                                      |
| --------------------- | ----------------------------------------------------------------------------------------------------- |
| open anyway           | `/manual/tasks/first-open/`                                                                           |
| cannot verify         | `/manual/tasks/first-open/` or `/manual/troubleshooting/`                                             |
| damaged               | `/manual/troubleshooting/`                                                                            |
| intel                 | `/manual/getting-started/` or `/manual/faq/`                                                          |
| macos version         | `/manual/getting-started/`, `/manual/faq/`, or `/download/`                                           |
| no voice is installed | `/manual/troubleshooting/` or `/manual/reference/status-messages/`                                    |
| download voices       | `/manual/tasks/voices-and-storage/` or `/manual/getting-started/`                                     |
| offline               | `/manual/tasks/work-offline/`                                                                         |
| privacy               | `/about/privacy/`                                                                                     |
| keyboard shortcuts    | `/manual/reference/keyboard-shortcuts/`                                                               |
| rotation              | `/manual/tutorials/voice-rotation/` or `/manual/reference/voices/`                                    |
| men only              | `/manual/reference/voices/`                                                                           |
| fraction              | `/manual/reference/pronunciation-examples/`                                                           |
| bracket               | `/manual/reference/pronunciation-guides/`                                                             |
| KREBZ                 | `/manual/tutorials/fix-a-word/` or `/manual/reference/pronunciation-guides/`                          |
| answer line           | `/manual/tasks/practice-alone/`, `/manual/reference/window/`, or `/manual/reference/question-format/` |
| no sound              | `/manual/troubleshooting/`                                                                            |
| self-test             | `/manual/reference/command-line/` or `/manual/get-help/`                                              |
| uninstall             | `/manual/tasks/install/`                                                                              |
| GPL                   | `/about/licenses/`                                                                                    |

For "macos version", the FAQ and Download pages count as correct as well as Get started, by the
lead's decision: both link to "Check your Mac" on Get started in one click.

## Custom domain

The custom domain `cloudyreader.com` is set in **Settings > Pages**. This is the state on
2026-11-05:

| Part                                  | State                                                                                                           |
| ------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Custom domain in **Settings > Pages** | Set to `cloudyreader.com`.                                                                                      |
| DNS records                           | Done. The apex has four `A` records for the GitHub Pages addresses. `www` is a `CNAME` to `kiwee-co.github.io`. |
| GitHub DNS check                      | GitHub reports the domain valid.                                                                                |
| Certificate                           | GitHub reports it approved.                                                                                     |
| Domain verification                   | Open. It is optional and happens at organization level.                                                         |
| Enforce HTTPS                         | Open. Turn it on after the site is live.                                                                        |

With **GitHub Actions** as the source, the custom domain lives only in **Settings > Pages**.
GitHub ignores a `CNAME` file in the published artifact, so `site/public/CNAME` is a record of the
name, not a setting. GitHub redirects the project address, `kiwee-co.github.io/CloudyReader/`, to
the custom domain. The site uses root-relative links, so it works at the root of the domain.

Three steps remain:

| Step                    | State          | Where                           | What it does                                        |
| ----------------------- | -------------- | ------------------------------- | --------------------------------------------------- |
| 1. Verify the domain    | Open, optional | GitHub organization settings    | Reserves `cloudyreader.com` for the organization.   |
| 2. Keep the DNS records | Done           | The DNS host or registrar       | Points the name at GitHub Pages.                    |
| 3. Enforce HTTPS        | Open           | Repository **Settings > Pages** | Turns on HTTPS for the name, once the site is live. |

Do step 1 even though it is optional. DNS already points at GitHub Pages, so verification is the
protection against a takeover: it ties the name to the organization, and nobody else can serve the
name from another repository, even if the custom domain setting of this repository is cleared.

You need the Owner role in the `Kiwee-Co` organization and access to the DNS settings of
`cloudyreader.com`.

### Step 1. Verify the domain for the organization

1. Open the settings of the `Kiwee-Co` organization.
2. Under **Code, planning, and automation**, choose **Pages**.
3. Click **Add a domain** and enter `cloudyreader.com`.
4. GitHub shows a `TXT` record: a name and a value. The name is
   `_github-pages-challenge-Kiwee-Co.cloudyreader.com`. Add that record at the DNS host with the
   value that GitHub shows.
5. Wait until the record is visible:

   ```bash
   dig _github-pages-challenge-Kiwee-Co.cloudyreader.com +short -t TXT
   ```

6. Return to the Pages settings and click **Verify**.

Keep the `TXT` record after the verification. GitHub checks it again from time to time. Verifying
`cloudyreader.com` also covers its immediate subdomains, such as `www`.

Some DNS hosts want the full name in the host field. Others add the domain themselves, so you enter
only `_github-pages-challenge-Kiwee-Co`. If the check fails, run `dig` and look for a doubled
`cloudyreader.com.cloudyreader.com`.

### Step 2. Keep the DNS records

These records are in place at the DNS host. The host field for the apex is `@`, empty, or
`cloudyreader.com`, depending on the host.

| Type    | Host  | Value                |
| ------- | ----- | -------------------- |
| `A`     | apex  | `185.199.108.153`    |
| `A`     | apex  | `185.199.109.153`    |
| `A`     | apex  | `185.199.110.153`    |
| `A`     | apex  | `185.199.111.153`    |
| `CNAME` | `www` | `kiwee-co.github.io` |

The `CNAME` target is the organization address without the repository name. The apex is the custom
domain, so GitHub redirects `www.cloudyreader.com` to it.

`AAAA` records are optional. None are set, and the site works without them. To add IPv6, create
four `AAAA` records for the apex: `2606:50c0:8000::153`, `2606:50c0:8001::153`,
`2606:50c0:8002::153`, and `2606:50c0:8003::153`.

Keep these conditions true:

- The apex has no other `A`, `AAAA`, `ALIAS`, `ANAME`, or `CNAME` record. A parking-page record
  from the registrar is the usual culprit.
- The zone has no wildcard record such as `*.cloudyreader.com`. A wildcard can expose subdomains
  to takeover.
- If the domain has `CAA` records, one of them allows Let's Encrypt, for example
  `0 issue "letsencrypt.org"`. GitHub gets its certificates from Let's Encrypt.
- If the DNS host offers a proxy or CDN, the records stay on "DNS only".

Check the addresses against GitHub's documentation:
[Managing a custom domain for your GitHub Pages site](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site).
The Pages address resolves to the same set:

```bash
dig kiwee-co.github.io +short -t A
dig kiwee-co.github.io +short -t AAAA
```

### Step 3. Turn on HTTPS

1. Wait until the site shows its home page at `http://cloudyreader.com/`.
2. Open **Settings > Pages** in the repository.
3. Check that the DNS check succeeded and that GitHub issued the certificate.
4. Select **Enforce HTTPS**.

GitHub documents up to 24 hours for DNS changes to take effect. Often it takes minutes. After you
select the box, check both schemes:

```bash
curl -sI http://cloudyreader.com/ | head -n 1
curl -sI https://cloudyreader.com/ | head -n 1
```

The first command prints a redirect, such as `HTTP/1.1 301 Moved Permanently`. The second prints
`HTTP/2 200`.

## Check DNS with dig

Check the apex and `www`:

```bash
dig cloudyreader.com +noall +answer -t A
dig cloudyreader.com +noall +answer -t AAAA
dig www.cloudyreader.com +noall +answer
dig cloudyreader.com +noall +answer -t CAA
```

The apex `A` query returns the four IPv4 addresses. The TTL values vary:

```text
cloudyreader.com.      3600  IN  A      185.199.108.153
cloudyreader.com.      3600  IN  A      185.199.109.153
cloudyreader.com.      3600  IN  A      185.199.110.153
cloudyreader.com.      3600  IN  A      185.199.111.153
```

The `www` query returns the `CNAME` and then the four addresses behind it:

```text
www.cloudyreader.com.  3600  IN  CNAME  kiwee-co.github.io.
kiwee-co.github.io.    3600  IN  A      185.199.108.153
kiwee-co.github.io.    3600  IN  A      185.199.109.153
kiwee-co.github.io.    3600  IN  A      185.199.110.153
kiwee-co.github.io.    3600  IN  A      185.199.111.153
```

The `AAAA` query returns nothing, because no `AAAA` records are set. The `CAA` query returns
nothing, or a record that allows `letsencrypt.org`.

A DNS answer can lag by the old record's TTL. If the DNS host lets you, lower the TTL of a record
before you replace it. `dig` shows what your own resolver sees. Another resolver can answer
differently until the change spreads.

## Read the DNS check in Settings > Pages

GitHub shows the check result under **Custom domain**. GitHub words these messages in its own way
and can change them. Match by meaning.

| What Settings > Pages shows                                                                      | What it means                                                                | What to do                                                                                                          |
| ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| DNS check in progress                                                                            | GitHub is checking the records.                                              | Wait a few minutes. Reload the page.                                                                                |
| DNS check successful                                                                             | The records point at GitHub Pages. GitHub can request the certificate.       | Wait for the certificate. Then enforce HTTPS.                                                                       |
| DNS check unsuccessful: "Domain does not resolve to the GitHub Pages server"                     | The name resolves, but not to the GitHub Pages addresses.                    | Compare the `dig` output with the table in step 2. Remove stale `A` and `AAAA` records. Turn off a proxy.           |
| DNS check unsuccessful: "Domain's DNS record could not be retrieved"                             | GitHub got no DNS answer for the name.                                       | Check the spelling. Check that the records live at the DNS host that the registrar points to. Wait for propagation. |
| DNS check unsuccessful: "Both cloudyreader.com and its alternate name are improperly configured" | Neither the apex nor `www` passes.                                           | Fix the apex records and the `www` `CNAME`.                                                                         |
| DNS check unsuccessful, with a message about `www` and a `CNAME` record                          | The `www` record is missing, or it is not a `CNAME` to `kiwee-co.github.io`. | Add or fix the `www` record.                                                                                        |
| **Enforce HTTPS** unavailable: a certificate has not yet been issued                             | GitHub waits for a passing DNS check, then issues the certificate.           | Wait. Reload the page.                                                                                              |
| **Enforce HTTPS** unavailable: the domain is not properly configured to support HTTPS            | The DNS check fails, or a `CAA` record blocks Let's Encrypt.                 | Fix the DNS records. Allow `letsencrypt.org` in `CAA`.                                                              |
| A message that another repository or account uses the domain                                     | Another site claims the name.                                                | Verify the domain for the organization (step 1). If the message stays, contact GitHub support.                      |

## Do not use a registrar redirect

Many registrars offer "URL forwarding" or "redirect" for a domain. Do not use it here. Use the DNS
records above.

- **No certificate.** A forwarding service answers for the name on its own servers. GitHub never
  sees DNS that points at its servers, so Pages cannot issue a certificate for the name, and
  `https://` fails or shows a warning.
- **A loop.** GitHub redirects `kiwee-co.github.io/CloudyReader/` to `cloudyreader.com`. A registrar
  redirect from `cloudyreader.com` back to `kiwee-co.github.io/CloudyReader/` sends the browser
  around forever.
- **A wrong address bar.** A forward changes the address that visitors see and share.

With DNS records, the browser connects to GitHub directly. GitHub presents the certificate for the
name. There is a single hop.

## Fix common errors

| Symptom                                 | Likely cause                                                                                             | Fix                                                                                         |
| --------------------------------------- | -------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| The Pages settings report a DNS problem | A missing record, a typo, or a stale `A` record                                                          | Compare `dig` output with the table in step 2. Delete the stale record.                     |
| The domain stays unverified             | A wrong `TXT` name or value, or a doubled domain in the name                                             | Run the `dig` query from step 1. Fix the record.                                            |
| **Enforce HTTPS** stays unavailable     | The certificate is pending, a `CAA` record blocks Let's Encrypt, or a proxy sits in front of the records | Wait. Allow `letsencrypt.org` in `CAA`. Set the records to "DNS only".                      |
| GitHub shows a 404 page on the name     | The Pages workflow failed, or the source is not **GitHub Actions**                                       | Open **Actions > Pages** and read the latest run. Check the source in **Settings > Pages**. |
| `www` shows a certificate warning       | The `www` record is missing, or it is not a `CNAME` to `kiwee-co.github.io`                              | Add or fix the record.                                                                      |
| The browser reports too many redirects  | A registrar redirect points back at the project address                                                  | Remove the redirect. Use the DNS records.                                                   |

To undo the custom domain, clear **Custom domain** in **Settings > Pages**, then remove the records
from the DNS host.
