# Adding the 🐝 Hive button to longevity.ge headers

The longevity.ge family runs on OJS 3.5 (PKP). Each journal has its
own theme. The cleanest place to add a navigation link to
`https://hive.longevity.ge` is via the OJS Custom Block plugin OR
direct theme-template edit.

## Option A — Custom Header Block (recommended, no theme fork)

1. Log into OJS as journal manager.
2. **Settings → Website → Plugins → Generic Plugins** — enable
 "Custom Block Manager" if not already.
3. **Settings → Website → Setup → Sidebar Management** → add new
 custom block "Hive Link", body:

 ```html
 <a href="https://hive.longevity.ge"
 target="_blank" rel="noopener"
 style="display:inline-block;padding:6px 12px;
 background:#c97f00;color:#fff;
 border-radius:4px;text-decoration:none;
 font-weight:500;">
 🐝 Hive
 </a>
 ```

4. Position the block in the header sidebar.

Repeat for each journal context (Annals + Longevity Horizon).

## Option B — Theme template edit (if Option A unavailable)

For OJS default theme, the header file is:

```
lib/pkp/templates/frontend/components/header.tpl
```

OR theme-specific override in `plugins/themes/<theme>/templates/frontend/components/header.tpl`.

Add inside the `<nav>` block:

```html
<li class="custom-link">
 <a href="https://hive.longevity.ge" target="_blank" rel="noopener">
 🐝 Hive
 </a>
</li>
```

Then clear OJS template cache:

```bash
ssh jaba@server "cd /home/jaba/web/longevity && \
 rm -rf cache/t_compile/* && \
 sudo systemctl reload php8.4-fpm"
```

## Option C — nginx-level injection (across ALL longevity.ge paths)

For a one-shot, theme-agnostic banner across `longevity.ge/`,
`longevity.ge/longhoriz/`, and `longevity.ge/rescience/`, use nginx
sub_filter on HTML responses (only if `ngx_http_sub_module` is
compiled in — verify with `nginx -V`):

```nginx
# inside the longevity.ge server block
sub_filter '</body>'
 '<a href="https://hive.longevity.ge"
 style="position:fixed;bottom:14px;right:14px;
 padding:10px 16px;background:#c97f00;color:#fff;
 border-radius:24px;text-decoration:none;
 font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,.15);
 z-index:9999;">
 🐝 Hive</a></body>';
sub_filter_once on;
sub_filter_types text/html;
```

This adds a floating bottom-right button on every page without
touching OJS internals.

## Verification

After install, visit:
- `https://longevity.ge/` — see Hive link/button
- `https://longevity.ge/longhoriz/` — same
- `https://longevity.ge/rescience/` — same
- Click → lands at `https://hive.longevity.ge` (queen landing)
