# OpenVPN Control Interface System

## Direction and feel

- Audience: VPN and infrastructure administrators who need to scan tunnel health, manage multiple OpenVPN instances, upload trust material, export client profiles, and audit sessions.
- Feel: calm, trustworthy operations workspace with editorial clarity. It should feel closer to a well-organized runbook than a dark terminal.
- Signature: the overview begins with a deep-navy tunnel signal strip combining live status, a connection waveform, and the two most important counters.
- Source direction: `DESIGN.md`.

## OpenVPN OAuth2 implementation boundary

- This repository uses OAuth2 as its only identity source. Do not add LDAP source configuration, LDAP forms, or LDAP status treatments.
- The current runtime is one OpenVPN instance per container. The UI represents the instance as `default`; Docker Compose owns the container lifecycle, while the persistent internal controller owns the OpenVPN/OAuth2 child-process lifecycle. The Web UI may start, stop, restart, and reload the child processes without terminating PID 1 or the administration console.
- Connection and traffic audit, certificates, client profiles, local documentation, GeoIP settings, and branding follow the full interface system below.
- Multi-instance creation, instance lock protection, and LDAP-specific fields remain reference patterns for repositories that actually provide those server capabilities; they are not simulated here.

## Color system

Use semantic tokens rather than adding page-specific colors.

- Canvas: `#f8f7f5`
- Panel: `#ffffff`
- Raised surface: `#f6f5f4`
- Inset control surface: `#f1f0ee`
- Primary ink: `#1a1a1a`
- Secondary ink: `#5d5b54`
- Tertiary ink: `#787671`
- Muted ink: `#a4a097`
- Command blue: `#2563eb`
- Command pressed: `#1d4ed8`
- Blue selection/tint: `#dbeafe`
- Tunnel navy: `#0a1530`
- Success: `#1aae39`; success tint: `#d9f3e1`
- Warning: `#dd5b00`; warning tint: `#ffe8d4`
- Destructive: `#e03131`
- Supporting instance tints: sky `#dcecfa`, mint `#d9f3e1`, blue `#dbeafe`

Blue is reserved for commands, focus, and selected navigation. Green, orange, and red are reserved for semantic state. The navy band is the only strongly dark surface.

## Depth and surfaces

- Strategy: light borders plus very subtle shadows. Do not mix in dramatic elevation.
- Standard border: `rgba(55,53,47,.10)`
- Emphasized/control border: `rgba(55,53,47,.20)`
- Standard panel shadow: `0 1px 2px rgba(15,15,15,.03)`
- Tunnel strip shadow: `0 12px 32px -20px rgba(10,21,48,.55)`
- Dialog shadow: `0 16px 48px -8px rgba(15,15,15,.18)`
- Sidebar shares the canvas color and is separated by one quiet border.
- Inputs are inset and slightly darker than panels.

## Geometry and spacing

- Base spacing unit: `4px`.
- Common gaps: `8px`, `12px`, `16px`, `24px`, `32px`, `40px`.
- Button/input radius: `8px`.
- Card radius: `12px`.
- Dialog and tunnel-strip radius: `16px`.
- Sidebar width: `248px`.
- Top bar: `96px` desktop, `84px` mobile.
- Main view: maximum `1440px`; desktop padding `32px 36px 64px`; mobile padding `24px 16px 48px`.
- Dense data rows use 12–16px vertical padding; major sections use 32–40px separation.

## Typography and hierarchy

- UI stack: `"Notion Sans", Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans SC", sans-serif`.
- Technical values: `"SFMono-Regular", "Cascadia Code", Consolas, monospace`.
- Base body: `15px`.
- Eyebrow: `11px`, tracked uppercase, command blue.
- Page title: `28px / 600`, tight negative tracking.
- Section/card title: `20px / 600`.
- Body/supporting copy: `14px`; metadata: `11–12px`.
- Hero online count: `48px / 600`; responsive mobile size: `42px`.
- Dynamic counters and timestamps use tabular or monospace figures.
- Hierarchy should come from weight, contrast, and whitespace before adding size.

## Reusable component patterns

### Primary button

- `40px` height; `18px` horizontal padding; `8px` radius; `14px / 500`.
- Blue background with white text; pressed/hover state uses the darker blue.
- Focus ring: `2px` command blue with `2px` offset.

### Secondary button

- Same measurements as primary.
- White panel background with emphasized neutral border.
- Hover uses the raised warm-gray surface.

### Navigation item

- `44px` height; `8px` radius; `14px / 500`.
- Active state uses pale-blue fill and dark-blue text, with `600` weight.
- Mobile navigation becomes a `248px` off-canvas drawer; it must not increase document width.

### Panel and instance card

- `12px` radius, quiet border, and standard panel shadow.
- Panel header uses `16px 20px` padding and at least `76px` height.
- Instance cards may rotate blue, sky, and mint backgrounds to distinguish tunnels without introducing new accents.
- Instance rows place the configuration workflow on a full-width secondary row in this order: VPN service configuration, identity source configuration, certificate material, client profile. Lifecycle controls remain a separate group.
- VPN service configuration and identity source configuration belong to the VPN instance context, never the system-settings workspace. Each opens a native dialog; service configuration owns endpoint, tunnel, address-pool, NAT, routing, and IPv6 fields, while identity source owns OAuth2 provider, callback, client credentials, and management secrets.
- Runtime failures use an inline peach diagnostic area with a concise cause and expandable OpenVPN log tail; long failures must not rely on toast feedback alone.

### Tunnel signal strip

- Deep navy surface with white type.
- `16px` radius and `32px` desktop padding (`24px` mobile).
- Blue/green waveform signals connection activity.
- At narrow desktop widths the waveform may hide before the critical counters do.

### Forms and dialogs

- Inputs: `40px` height, `8px` radius, inset warm-gray fill.
- Select: use the shared accessible custom-select wrapper rather than the browser-native popup. The trigger is `44px` high with `8px` radius, white panel fill, `14px / 500` text, and the standard command-blue focus ring. The hidden native select remains the source of truth for form submission and existing change handlers.
- Select menu: fixed-position white raised surface, `8px` radius, `4px` inner padding, quiet border, and subtle shadow. Options are at least `36px` high; hover uses raised warm-gray, while the selected option uses pale blue with dark-blue text and a checkmark. Support click-outside close, Escape, Enter/Space, arrow navigation, and viewport-aware above/below placement.
- At `760px` and below, filter bars containing selects use a one-column layout; controls fill the available width and must not cause horizontal scrolling.
- Dialog: `16px` radius, `32px` viewport gutter, sticky action row on mobile.
- Instance configuration dialogs use the shared form controls. The VPN service dialog may expand to `760px`; group service endpoint and routing/IPv6 fields with quiet fieldsets, and keep the action row visible within the viewport.
- Start, stop, restart, and reload always use the shared confirmation dialog. The dialog names the target instance, explains session impact, and changes the final action to destructive red only for stop.
- Desktop form fields may use two columns; collapse to one below `760px`.
- File upload, routing, certificate, and OAuth2 controls reuse the same input/focus tokens.
- Client configuration separates TLS certificate validation, OAuth2 identity authentication, and traffic rules into distinct fieldsets.
- TLS direction is explicit: client-to-server certificate validation is always enabled; server-to-client certificate requirements use the switch-card pattern.

### Status treatment

- Prefer a small semantic dot plus text or a compact pastel badge.
- Never rely on color alone; always keep the state label.
- Success uses green/mint, warning uses orange/peach, destructive uses red.
- Global toast feedback uses a manual popover so it remains above modal dialog backdrops; keep it fixed to the lower-right viewport gutter.
- Instance lock: the instance heading exposes one explicit lock/unlock control. A locked instance shows a compact neutral `锁定保护` badge and disables service configuration, identity-source configuration, start, stop, restart, and reload with a clear explanation. Protection must also be enforced by the server with a locked response, not only by disabled controls.

### Traffic geography

- The traffic-audit view may add a destination-only geography row before trend analysis. It uses a quiet equirectangular grid with blue proportional dots, not decorative route arcs or an invented VPN-origin location.
- Pair the map with a compact country/region ranking; dots and rank bars use command blue, while the map grid stays neutral and recedes behind the data.
- GeoIP is optional. When unavailable, retain the panel dimensions and show a clear offline-database setup message rather than an error state. Private/reserved IPs and unresolved destinations are omitted from the map.

### Traffic audit workspace

- Data source: capture decrypted VPN-side TCP/UDP metadata, direction-aware bytes, DNS response association, TLS SNI, and plaintext HTTP Host. Never present encrypted payload, HTTPS URL path, or body content as auditable data.
- The primary audit surface starts with a compact boundary note and capture-state badge, then a navy traffic ledger (total, download, upload, connections, domain/target count, identified users).
- The audit filter bar owns the query context: keyword, VPN instance, time range, and refresh cadence. All tabs use this same context.
- Use two local tabs directly below the filter context: `流量分析` for geography/trend/recent records and `访问目标总览` for the complete aggregated target table. Tabs are quiet text controls with a command-blue 2px active underline; do not introduce a second navigation system.
- `访问目标总览` is a dense, horizontally scrollable data table. It groups recognized domains or fallback target IPs and shows associated IPs, user count, upload, download, connections, and last-seen time. The total target count belongs in the panel-header badge.
- The GeoIP action is a secondary button in the traffic-audit heading, alongside CSV export. It opens the shared dialog pattern and never competes with the page title or primary analysis metrics.
- GeoIP dialog fields: GitHub repository (`owner/repository`), ref, database file, update frequency in hours (`0` disables scheduled updates), and access-record retention days. Use the existing two-column form grid and native form semantics; saving shows toast feedback and immediately refreshes audit data.
- GeoIP defaults to `Loyalsoldier/geoip@release/Country.mmdb`, validates the accompanying SHA-256 file, writes atomically, and hot-reloads when the database mtime changes. Country MMDB provides country/region attribution only: retain the country ranking and state that city points are unavailable instead of inventing coordinates.
- Access-record retention is configurable from 1 to 3650 days. Saving applies cleanup immediately; every subsequent ingestion also enforces the saved policy.

## Current product capabilities

- Container-managed single-instance OpenVPN runtime, OAuth2 authentication, certificate readiness, client profile export, runtime health, local documentation, and persistent branding.
- Web-managed system settings cover the OpenVPN endpoint/address pool, DNS/NAT, IPv6, certificate bootstrap, OAuth2 provider, encrypted OAuth2 secrets, traffic capture, and console credentials. Environment variables are reserved for the encryption root key, first-login password, fixed Web listener, and persistent-path wiring.
- Connection audit records connect/disconnect events, source address, VPN address, transferred bytes, session duration, and CSV export.
- Traffic audit records identity, VPN IP, destination IP/port/protocol, inferred domain, upload/download, and approximate connection counts; it provides live refresh, trend analysis, destination ranking, country-level GeoIP ranking, geography state, CSV export, and full target inventory.
- GeoIP source and update cadence are runtime-configurable from the traffic-audit UI. The shared settings file is read by the updater so source/frequency changes take effect without a container restart.

### System settings workspace

- Navigation places `系统设置` immediately before branding. Its focal element is a compact configuration-policy panel explaining what is Web-managed, what is encrypted, and which changes require a container restart.
- Configuration is limited to cross-instance runtime policy, audit behavior, and console security. OpenVPN service, routing/IPv6, and OAuth2 identity-source fields live in the VPN instance dialogs. Never expose LDAP fields.
- Reuse the shared two-column form grid, accessible custom selects, and switch-row pattern. Below 1050px the panels become one column; below 760px every field becomes one column.
- Each panel carries an explicit `即时生效` or `重启后生效` badge. A sticky save bar summarizes unsaved state and the resulting activation boundary.
- OAuth2 Client Secret and HTTP session Secret use password inputs with “leave blank to retain” behavior. The API returns only configured/unconfigured state. Persistent secrets are AES-256 encrypted using the container-provided root key.
- Console passwords are never encrypted reversibly: persist only a salted PBKDF2-SHA256 hash. The environment bootstrap password remains a first-login fallback until a Web-managed password is saved.
- The Web listener and encryption root key cannot move into runtime configuration because the console and decryptor need them before the settings database is available. Keep those bootstrap dependencies visibly documented rather than pretending they are hot-configurable.

### Console login

- Authentication uses a first-party HTML login page, never the browser-native HTTP Basic Auth prompt.
- The page stays in the warm-gray operations world: a white form panel is the focal surface and a single tunnel-navy companion panel explains the `ADMIN → OAUTH2 → VPN` control path.
- Login fields are 46px inset controls with native labels, autocomplete semantics, visible focus, an explicit password-visibility control, inline error feedback, and a 44px command-blue submit button.
- Desktop uses a balanced two-panel card capped at 920px. Below 820px it becomes one column; below 520px it uses a 16px viewport gutter without horizontal overflow.
- Successful authentication creates an HttpOnly, SameSite=Strict session cookie with a fixed 12-hour maximum lifetime. Repeated failures are rate-limited; logout explicitly invalidates the server-side session.
- The app top bar keeps logout as a compact icon action after refresh. Expired API sessions redirect to `/login` while preserving a same-origin return path.

## Complete UI inventory and functional specification

### Application shell

- Desktop shell: quiet canvas sidebar (248px) + top bar (96px) + one active content view. The sidebar is navigation, not a separate visual world; use only its boundary to separate it from content.
- Mobile shell: the same sidebar becomes a 236px off-canvas drawer; the content column must remain within the viewport at 390px.
- Global top bar: current view title, live clock, theme/language controls where present, and logout. Keep operational controls inside their relevant views instead of crowding the top bar.
- Navigation views: 总览, VPN 实例, 连接审计, 流量审计, 证书管理, 本地文档, 品牌设置. Active navigation uses pale-blue fill, dark command blue text, and a 600 weight.
- All loading, empty, unavailable, and failure states use a concise heading plus one practical next action. Do not leave a blank panel.

### Overview

- Focal element: the navy tunnel signal strip. It communicates service state, online sessions, activity waveform, and the highest-value counters at a glance.
- Supporting areas: instance cards, current online-session table, and recent cross-instance connection events.
- Instance cards use restrained sky/mint/blue tints only to distinguish tunnels; service status remains semantic dot + label rather than decorative color.
- Recent activity is a compact handoff into connection audit, not a second full audit table.

### VPN instance management

- Primary task: configure, start, stop, restart, reload, lock, and unlock the `default` OpenVPN instance safely.
- List rows expose service state, address pool, protocol/port, online count, certificate readiness, and lifecycle actions. Keep configuration and destructive lifecycle controls visually separate.
- The heading supplies a quiet lock/unlock control. A locked instance has an explicit protection badge and server-enforced disabled configuration and lifecycle actions.
- Instance configuration is split into two entry points: VPN service configuration for endpoint/network/routing, and identity source configuration for OAuth2. Both use two-column desktop fields and one-column mobile fields.
- Client-profile dialog exposes endpoint, VPN network, certificate posture, generated `.ovpn` export, full-tunnel routing, DNS, VPN routes, IPv6 routes, and bypass routes. Routing lists use indexed, editable rows and compact remove controls.

### Connection audit

- Purpose: connection-level accountability, separate from destination traffic analysis.
- Filter bar: keyword search, instance, event type, time range, and refresh cadence; use the shared custom-select behavior and preserve native form values.
- Table fields: time, connect/disconnect event, user, instance, source address, VPN IP, received/sent bytes, and session duration.
- CSV export mirrors the active filter context.

### VPN instance lifecycle

- The operations console is the persistent control plane; stopping the VPN data plane must never make the console unavailable.
- The instance page shows one authoritative textual state: running, starting, stopping, stopped, failed, or controller unavailable.
- Lifecycle controls are grouped in a dedicated neutral strip below the instance identity. Order is start, restart, reload, stop; stop uses the outlined danger treatment.
- Start is disabled while running/starting. Stop is disabled while stopped/stopping. Restart and stop warn that active VPN sessions will disconnect.
- Reload is available only while running and signals the OpenVPN process without stopping the OAuth2 child process or administration console.
- Every lifecycle action requires the shared confirmation dialog before the request is sent.
- A stopped instance uses neutral gray rather than red. Red is reserved for a failed instance or unavailable controller.
- Supporting copy must state that stop affects only OpenVPN/OAuth2 child processes and that the Web console remains accessible.

### Traffic audit

- Purpose: destination-level traffic attribution within VPN-visible TCP/UDP metadata.
- Header actions: secondary `GeoIP 配置` then secondary `导出 CSV`; destructive or primary actions do not belong here.
- Information boundary: explain that DNS, TLS SNI, and HTTP Host can infer domains; encrypted HTTPS contents and URL paths are not collected. ECH and direct-IP traffic may remain IP-only.
- Filter context: keyword, VPN instance, time range, and refresh cadence. Search matches user, domain, and destination IP.
- Ledger: a single navy strip with total traffic as the visual lead, followed by download, upload, connections, domain/target count, and identified users.
- Analysis tab sections, in order: GeoIP geography + country rank, traffic trend + destination rank, then recent raw access records.
- Target overview tab: full grouped inventory of domains/IPs; fields are target, type/associated IPs, users, upload, download, connections, and last seen. Keep it table-first and dense.
- CSV export is raw access detail, while target overview is an in-product aggregate.
- Capture-state badge is always textual: running, waiting, disabled, or failed; use semantic styling as a supplement only.

### GeoIP configuration dialog

- Entry point: traffic-audit header, opened by a secondary button.
- Form fields: GitHub repository, ref, MMDB file, update interval in hours, and audit-retention days.
- Validation rules: repository uses `owner/repository`; update interval is 0-8760; retention is 1-3650 days; file/ref cannot traverse paths.
- Save behavior: source/frequency writes to the shared GeoIP settings file; updater adopts it without restart. Retention saves to audit metadata and immediately removes expired access records.
- Geographic display policy: the default `Country.mmdb` is country-level only. Show country ranking and a precise country-level explanatory state; never display fabricated city points.

### Certificate management

- Full-width scan-friendly certificate-entry list with readiness, assigned instance count, file completeness, metadata, and one clear management action per row.
- Add/edit opens the certificate dialog. Upload controls remain in the dialog; the list never embeds a long form.
- Certificate workflow states use success green for validated material and warning orange for missing/incomplete material, always with a textual label.

### Local documentation and branding

- Local documentation renders managed Markdown with a stable table of contents and restrained reading width. It is a runbook surface, not a marketing page.
- Branding settings are a separate administrative view for brand name, banner/title, descriptive copy, copyright, logo, and banner assets. Preview is immediate; asset validation and size limits are explicit.

### Interaction and accessibility contract

- All buttons are native buttons; dialogs are native `<dialog>` elements with close controls, Escape behavior, focus-visible states, and sticky mobile action rows.
- Every select uses the shared custom-select wrapper: keyboard arrows, Enter/Space, Escape, click-outside close, viewport-aware menu placement, and a hidden native select as the source of truth.
- Tables preserve column semantics, use monospace/tabular figures for technical values, and gain horizontal scroll rather than compressing critical data beyond readability.
- Button states: default, hover, active, disabled, and focus-visible. Save actions disable while in flight and use toast/inline error feedback after resolution.
- Refresh timers run only for the visible authenticated view. Changing a filter refreshes the active audit data immediately.

### Certificate entries

- Certificate management is a full-width, scan-friendly list with file completeness, assigned-instance count, readiness, and one management action per row.
- Creating or rotating a certificate opens the shared native dialog; file uploads never remain embedded beside the list.
- Each entry shows readiness and assigned-instance count; missing material uses warning orange, validated material uses success green.
- Instance service configuration selects a certificate entry explicitly. Existing root-level certificates remain represented as the `default` entry.

## Responsive rules

- Below `1050px`: reduce multi-column content to one column where readability benefits; hide the decorative tunnel waveform before hiding data.
- Below `760px`: use the off-canvas navigation, one-column forms/cards, compact top bar, and full-width critical dialog actions.
- Minimum interactive target is `40px`; use `44px` for navigation.
- Every screen must pass a `390px` viewport check with no horizontal overflow.

## Guardrails

- Do not return to a full dark “hacker terminal” theme.
- Do not use generic grids of identical KPI cards; keep the tunnel strip as the overview focal point.
- Do not add gradients or decorative colors.
- Do not invent new radii, hard shadows, or arbitrary spacing values.
- Preserve native semantic controls and visible focus states.
- Verify desktop, approximately 1000px, and 390px mobile layouts after non-trivial UI changes.
