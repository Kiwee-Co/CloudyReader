---
title: 'Point cloudyreader.com at the site'
description: 'What is set for the custom domain, what is left, and how to check DNS and HTTPS.'
sidebar:
  order: 15
  label: 'Custom domain'
---

The custom domain `cloudyreader.com` is set in **Settings > Pages**. GitHub builds the site from the branch `main`, folder `/docs`. DNS already points the name at GitHub Pages. This guide lists what is done, what is left, and how to check each part.

The commands on this page are untested: CI does not run them.

## Know the current state

This is the state on 2026-11-05.

| Part | State |
| --- | --- |
| Custom domain in **Settings > Pages** | Set to `cloudyreader.com`. GitHub recorded it in `docs/CNAME`. |
| DNS records | Done. The apex has four `A` records for the GitHub Pages addresses. `www` is a `CNAME` to `kiwee-co.github.io`. |
| GitHub DNS check | GitHub reports the domain valid. |
| Certificate | GitHub reports it approved. |
| Domain verification | Open. It is optional and happens at organization level. |
| Enforce HTTPS | Open. Turn it on after the site is live. |

- **Do not edit or delete `docs/CNAME`.** GitHub created the file and reads it.
- GitHub redirects the project address, `kiwee-co.github.io/CloudyReader/`, to the custom domain.
- The pages use relative links, so they work at the root of the custom domain.

## Plan the remaining steps

| Step | State | Where | What it does |
| --- | --- | --- | --- |
| 1. Verify the domain | Open, optional | GitHub organization settings | Reserves `cloudyreader.com` for your organization. |
| 2. Set the DNS records | Done | Your DNS host or registrar | Points the name at GitHub Pages. |
| 3. Enforce HTTPS | Open | Repository **Settings > Pages** | Turns on HTTPS for the name, once the site is live. |

Do step 1 even though it is optional. DNS already points at GitHub Pages, so verification is the protection against a takeover. It ties the name to your organization. If the claim in the repository ever lapses, nobody else can serve the name from another repository. A lapse happens, for example, when someone deletes `docs/CNAME`.

You need the Owner role in the `Kiwee-Co` organization and access to the DNS settings of `cloudyreader.com`.

## Step 1. Verify the domain for the organization

1. Open the settings of the `Kiwee-Co` organization.
2. Under **Code, planning, and automation**, choose **Pages**.
3. Click **Add a domain** and enter `cloudyreader.com`.
4. GitHub shows a `TXT` record: a name and a value. The name is `_github-pages-challenge-Kiwee-Co.cloudyreader.com`. Add that record at your DNS host with the value that GitHub shows.
5. Wait until the record is visible:

   ```bash
   dig _github-pages-challenge-Kiwee-Co.cloudyreader.com +short -t TXT
   ```

6. Return to the Pages settings and click **Verify**.

Keep the `TXT` record after the verification. GitHub checks it again from time to time. Verifying `cloudyreader.com` also covers its immediate subdomains, such as `www`.

Some DNS hosts want the full name in the host field. Others add the domain themselves, so you enter only `_github-pages-challenge-Kiwee-Co`. If the check fails, run `dig` and look for a doubled `cloudyreader.com.cloudyreader.com`.

## Step 2. Know the DNS records (done)

These records are in place at the DNS host. The host field for the apex is `@`, empty, or `cloudyreader.com`, depending on the host.

| Type | Host | Value |
| --- | --- | --- |
| `A` | apex | `185.199.108.153` |
| `A` | apex | `185.199.109.153` |
| `A` | apex | `185.199.110.153` |
| `A` | apex | `185.199.111.153` |
| `CNAME` | `www` | `kiwee-co.github.io` |

The `CNAME` target is the organization address without the repository name. The apex is the custom domain, so GitHub redirects `www.cloudyreader.com` to it.

`AAAA` records are optional. None are set, and the site works without them. To add IPv6, create four `AAAA` records for the apex: `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, and `2606:50c0:8003::153`.

Keep these conditions true:

- The apex has no other `A`, `AAAA`, `ALIAS`, `ANAME`, or `CNAME` record. A parking-page record from the registrar is the usual culprit.
- The zone has no wildcard record such as `*.cloudyreader.com`. A wildcard can expose subdomains to takeover.
- If the domain has `CAA` records, one of them allows Let's Encrypt, for example `0 issue "letsencrypt.org"`. GitHub gets its certificates from Let's Encrypt.
- If your DNS host offers a proxy or CDN, the records stay on "DNS only".

Check the addresses against GitHub's current documentation. GitHub lists them in [Managing a custom domain for your GitHub Pages site](https://docs.github.com/en/pages/configuring-a-custom-domain-for-your-github-pages-site/managing-a-custom-domain-for-your-github-pages-site). The Pages address resolves to the same set:

```bash
dig kiwee-co.github.io +short -t A
dig kiwee-co.github.io +short -t AAAA
```

## Step 3. Turn on HTTPS

1. Wait until the site shows its home page at `http://cloudyreader.com/`.
2. Open **Settings > Pages** in the repository.
3. Check that the DNS check succeeded and that GitHub issued the certificate.
4. Select **Enforce HTTPS**.

GitHub documents up to 24 hours for DNS changes to take effect. Often it takes minutes. After you select the box, check both schemes:

```bash
curl -sI http://cloudyreader.com/ | head -n 1
curl -sI https://cloudyreader.com/ | head -n 1
```

The first command prints a redirect, such as `HTTP/1.1 301 Moved Permanently`. The second prints `HTTP/2 200`.

## Read the DNS check in Settings > Pages

GitHub shows the check result under **Custom domain**. GitHub words these messages in its own way and can change them. Match by meaning.

| What Settings > Pages shows | What it means | What to do |
| --- | --- | --- |
| DNS check in progress | GitHub is checking the records. | Wait a few minutes. Reload the page. |
| DNS check successful | The records point at GitHub Pages. GitHub can request the certificate. | Wait for the certificate. Then enforce HTTPS. |
| DNS check unsuccessful: "Domain does not resolve to the GitHub Pages server" | The name resolves, but not to the GitHub Pages addresses. | Compare the `dig` output with the table in step 2. Remove stale `A` and `AAAA` records. Turn off a proxy. |
| DNS check unsuccessful: "Domain's DNS record could not be retrieved" | GitHub got no DNS answer for the name. | Check the spelling. Check that the records live at the DNS host that your registrar points to. Wait for propagation. |
| DNS check unsuccessful: "Both cloudyreader.com and its alternate name are improperly configured" | Neither the apex nor `www` passes. | Fix the apex records and the `www` `CNAME`. |
| DNS check unsuccessful, with a message about `www` and a `CNAME` record | The `www` record is missing, or it is not a `CNAME` to `kiwee-co.github.io`. | Add or fix the `www` record. |
| **Enforce HTTPS** unavailable: a certificate has not yet been issued | GitHub waits for a passing DNS check, then issues the certificate. | Wait. Reload the page. |
| **Enforce HTTPS** unavailable: the domain is not properly configured to support HTTPS | The DNS check fails, or a `CAA` record blocks Let's Encrypt. | Fix the DNS records. Allow `letsencrypt.org` in `CAA`. |
| A message that another repository or account uses the domain | Another site claims the name. | Verify the domain for the organization (step 1). If the message stays, contact GitHub support. |

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

The `AAAA` query returns nothing, because no `AAAA` records are set. The `CAA` query returns nothing, or a record that allows `letsencrypt.org`.

A DNS answer can lag by the old record's TTL. If your DNS host lets you, lower the TTL of a record before you replace it. `dig` shows what your own resolver sees. Another resolver can answer differently until the change spreads.

## Do not use a registrar redirect

Many registrars offer "URL forwarding" or "redirect" for a domain. Do not use it here. Use the DNS records above.

- **No certificate.** A forwarding service answers for your name on its own servers. GitHub never sees DNS that points at its servers. So Pages cannot issue a certificate for the name, and `https://` fails or shows a warning.
- **A loop.** GitHub redirects `kiwee-co.github.io/CloudyReader/` to `cloudyreader.com`. A registrar redirect from `cloudyreader.com` back to `kiwee-co.github.io/CloudyReader/` sends the browser around forever.
- **A wrong address bar.** A forward changes the address that visitors see and share.

With DNS records, the browser connects to GitHub directly. GitHub presents the certificate for your name. There is a single hop.

## Fix common errors

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| The Pages settings report a DNS problem | A missing record, a typo, or a stale `A` record | Compare `dig` output with the table in step 2. Delete the stale record. |
| The domain stays unverified | A wrong `TXT` name or value, or a doubled domain in the name | Run the `dig` query from step 1. Fix the record. |
| **Enforce HTTPS** stays unavailable | The certificate is pending, a `CAA` record blocks Let's Encrypt, or a proxy sits in front of the records | Wait. Allow `letsencrypt.org` in `CAA`. Set the records to "DNS only". |
| GitHub shows a 404 page on the new name | The site build failed, or `docs/CNAME` is missing | Open the **Actions** tab and check the latest Pages build. Check that `docs/CNAME` exists. |
| `www` shows a certificate warning | The `www` record is missing, or it is not a `CNAME` to `kiwee-co.github.io` | Add or fix the record. |
| The browser reports too many redirects | A registrar redirect points back at the project address | Remove the redirect. Use the DNS records. |

To undo the change, clear **Custom domain** in **Settings > Pages**, then remove the records from your DNS host. Do not delete `docs/CNAME` by hand while the domain is set.
