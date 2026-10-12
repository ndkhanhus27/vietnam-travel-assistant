# README Asset Setup

This directory holds two screenshots used by the root README: desktop chat
and sign-in. No screenshots are included yet; add actual application captures.

## 1. Add the Screenshot

Place the image at `assets/demo-desktop-chat.png` (relative to the repository
root). Use PNG, ideally 1440-1920 pixels wide, with readable answer text.
Keep only the application viewport; exclude browser tabs and desktop clutter.
Hide account details and private conversation titles. Preserve data-availability
warnings rather than implying an unavailable feature succeeded.

Suggested request:

> Lên lịch Huế 3 ngày cuối tuần này, xem có mưa không, có sự kiện gì và từ Đại Nội đến lăng Khải Định đi mất bao lâu?

In the root `README.md`, replace `**Screenshot:** to be added.` with:

```markdown
![Desktop chat showing a compound travel request and source references](assets/demo-desktop-chat.png)
```

Keep the existing Figure 1 caption. If using JPG or a different filename,
update the image path to match exactly, including letter case.

### Add the Sign-in Screenshot

Place the second image at `assets/demo-sign-in.png`. Open `/login` while signed
out. Capture Google sign-in, the Gmail/password form, Forgot password, and
Create account in the same viewport. Configure Google sign-in first if the
button should be available; do not depict a disabled integration as functional.
Leave inputs empty and hide autofill, saved emails, and Google account popups.
Do not capture password-reset links or tokens.

In the root `README.md`, replace `**Sign-in screenshot:** to be added.` with:

```markdown
![Sign-in screen with Google and Gmail-password options](assets/demo-sign-in.png)
```

Keep the Figure 2 caption. No separate registration or recovery screenshot is
required; their behavior is documented under Authentication and Account Recovery.

## 2. Set the Demo URL

Under `## Live Demo` in the root `README.md`, replace
`**Demo URL:** to be added.` with:

```markdown
[Open live demo](https://YOUR_PUBLIC_DOMAIN)
```

Replace `YOUR_PUBLIC_DOMAIN` with the deployed domain. Verify that it opens
the application over HTTPS and does not contain credentials. This changes
documentation only; it does not configure DNS, TLS, Caddy, or application URLs.

## 3. Other Links

- Tech badges already link to their technology websites; no change is required.
- Documentation links use repository-relative paths; keep their target files.
- Mermaid diagrams render directly on GitHub; no diagram image files are needed.
- Remove the setup comments in the root README once the demo and image are added.

## 4. Publish

Review the rendered root README on GitHub after pushing. Confirm that the demo
link opens correctly and the screenshot is readable without horizontal scrolling.
The Markdown image path is relative to the root README, not this setup guide.

```powershell
git add README.md assets/README.md assets/demo-desktop-chat.png assets/demo-sign-in.png
git commit -m "docs: add live demo link and interface screenshots"
git push origin main
```

Run these commands only after adding both screenshots and updating the demo URL.
Do not force-push if the remote branch has changed; integrate its changes first.
