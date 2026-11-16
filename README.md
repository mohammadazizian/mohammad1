# Atlas CRM — CRM & Inventory Management System

An extensible, enterprise-style CRM and inventory system built with **.NET 10**, **ASP.NET Core Razor Pages**,
**Entity Framework Core 10** and **SQL Server**, structured as a strict **Clean Architecture** solution.
The UI is bilingual — **English (LTR, Inter)** and **Persian (RTL, Vazirmatn, Jalali calendar)** — and switches at runtime.

## Quick start

### Option A — Docker (recommended)

```bash
cp .env.example .env          # then change the passwords in .env
docker compose up --build
```

Open <http://localhost:8080> and sign in:

| User    | Password      | Role                 | Sees                                             |
|---------|---------------|----------------------|--------------------------------------------------|
| `admin` | `Admin@12345` | Administrator        | everything                                       |
| `sara`  | `Demo@12345`  | Sales Manager        | CRM, tasks, reports, the demo form               |
| `mina`  | `Demo@12345`  | Sales Representative | CRM (no delete), tasks                           |
| `reza`  | `Demo@12345`  | Warehouse Keeper     | products, inventory, tasks — no CRM, no admin    |

On start-up the app waits for SQL Server, **applies the EF Core migrations** and **seeds** roles and permissions, the
users above, a sales pipeline, products with stock in two warehouses, customers, leads, deals, tasks, chat messages and a
bilingual dynamic form ("Customer Site Visit Report" / «گزارش بازدید از مشتری») with one submission.

`docker compose down` stops the stack; add `-v` to also delete the database and upload volumes.

### Option B — .NET CLI

Requirements: .NET 10 SDK and a reachable SQL Server (2019+).

```bash
# 1. a SQL Server for development (skip if you already have one)
docker run -d --name crm-sql -e ACCEPT_EULA=Y -e 'MSSQL_SA_PASSWORD=Str0ng!Passw0rd' -p 1433:1433 \
       mcr.microsoft.com/mssql/server:2022-latest

# 2. build and run (migrations + seeding happen automatically)
dotnet restore
dotnet build
dotnet run --project src/Crm.WebUI --urls http://localhost:5080
```

`localhost` only accepts connections from the same machine. To open the app from other computers, listen on all
interfaces instead and browse to `http://<server-ip>:5080`:

```bash
dotnet run --project src/Crm.WebUI --urls http://0.0.0.0:5080
# or: dotnet run --project src/Crm.WebUI --launch-profile lan    (port 5059)
```

### Access from other machines (both options)

* The server's firewall must allow the port: Windows → *Windows Defender Firewall → Inbound rule → TCP 8080 / 5080*;
  Linux → `sudo ufw allow 8080/tcp`; cloud VMs → open the port in the security group / network firewall.
* Use the server's LAN or public IP, e.g. `http://192.168.1.20:8080` — not `localhost`, which on the other computer
  means that computer itself.
* Docker already publishes port 8080 on all interfaces (`APP_PORT` in `.env`). With Docker Desktop on Windows/macOS
  the host firewall still applies.
* **Docker inside WSL2:** WSL2 sits behind a NAT, so Windows forwards its ports to `localhost` only. Either enable
  mirrored networking (Windows 11 22H2+) — `networkingMode=mirrored` under `[wsl2]` in `%USERPROFILE%\.wslconfig`,
  then in an elevated PowerShell
  `Set-NetFirewallHyperVVMSetting -Name '{40E0AC32-46A5-438A-A0B2-2B479E8F2E90}' -DefaultInboundAction Allow`
  and `wsl --shutdown` — or forward the port:
  `netsh interface portproxy add v4tov4 listenport=8080 listenaddress=0.0.0.0 connectport=8080 connectaddress=<WSL IP>`
  (`wsl hostname -I`; the WSL IP changes after a reboot). In both cases add an inbound firewall rule for TCP 8080 and
  browse to the Windows IP from `ipconfig`.

The connection string lives in `src/Crm.WebUI/appsettings.json` (`ConnectionStrings:DefaultConnection`); override it
with the `ConnectionStrings__DefaultConnection` environment variable or user secrets.

EF Core tooling (pinned in `dotnet-tools.json`):

```bash
dotnet tool restore
dotnet ef migrations add <Name> -p src/Crm.Infrastructure -s src/Crm.WebUI -o Persistence/Migrations
dotnet ef database update      -p src/Crm.Infrastructure -s src/Crm.WebUI
```

## Architecture

```
src/
├─ Crm.Domain          Entities, value objects, enums, domain events, ITrackableEntity. No dependencies at all.
├─ Crm.Application     CQRS (MediatR), FluentValidation, DTOs, ports (interfaces), specifications, report engine.
├─ Crm.Infrastructure  EF Core 10 DbContext + configurations + migrations, interceptors, Identity & permissions,
│                      SignalR hubs, background worker, file storage, Excel/PDF exporters, data seeder.
└─ Crm.WebUI           Razor Pages, partials, ViewComponents, TagHelpers, .resx resources, static assets.
```

Dependencies point inwards only: `WebUI → Infrastructure → Application → Domain`.

| Concern | Where |
|---|---|
| CQRS + pipeline behaviours (validation, logging) | `Crm.Application/Features/*`, `Common/Behaviors` |
| Auditing, soft-delete, automatic activity log | `Infrastructure/Persistence/Interceptors/AuditableEntityInterceptor.cs` |
| Domain events → MediatR (low-stock alerts, stage changes) | `DispatchDomainEventsInterceptor.cs`, `Features/Inventory`, `Features/Deals` |
| Global exception handling (`IExceptionHandler`, ProblemDetails) | `WebUI/Support/GlobalExceptionHandler.cs` |
| Structured logging | Serilog, configured in `appsettings.json` |
| Specification pattern | `Application/Common/Specifications`, `Infrastructure/Persistence/EfReadRepository.cs` |

### Polymorphic entity engine

Anything that implements `ITrackableEntity` (`EntityType` + `Id`) gets **chat, tasks, reminders and an activity
timeline** without new tables: `ChatMessages`, `Tasks`, `Reminders` and `ActivityLogs` point at their owner through an
indexed `(EntityType, EntityId)` pair. Customers, products, inventory transactions, **dynamic form submissions**,
leads and deals are trackable today.

To make a new entity trackable: add a member to `TrackableEntityType`, implement the interface, add one case to
`TrackableEntityResolver` and one route to `EntityRoutes`, then drop
`<vc:entity-collaboration type="…" id="…" />` and `<vc:activity-timeline … />` on its page.

### EF Core 10 JSON columns

Mapped with EF Core 10 complex types (`ComplexProperty` / `ComplexCollection` + `ToJson()`):

* `FormDefinitions.Title`, `.Description` (localized text) and `.Fields` (the whole field schema, with nested options)
* `FormSubmissions.Values` (the answers)
* `ChatMessages.Attachments`; `ChatMessages.MentionedUserIds` is a JSON primitive collection

## Modules

* **CRM** — leads (convert to customer), customers (B2B/B2C) with contacts and interaction history, deals on a
  drag-and-drop Kanban pipeline.
* **Products & inventory** — catalogue, bilingual categories, SKU rules, multiple warehouses, stock levels, stock
  movements (in / out / transfer) with optimistic concurrency, low-stock alerts.
* **Contextual chat** — slide-over chat on every trackable object: real-time via SignalR, `@user` mentions with
  auto-complete and instant notifications, `#object` links, file attachments, thread replies, typing indicator.
* **Tasks & reminders** — tasks assigned to a user and/or a role and bound to any object; a hosted background service
  delivers due reminders as real-time notifications.
* **Dynamic form builder** — text, long text, number, dropdown, date, file and entity-lookup fields with validation
  rules and English/Persian labels. Every form gets its own menu entry, list, permissions and collaboration tools.
* **IAM** — ASP.NET Core Identity plus dynamic permission policies (`Permission:{Module}.{Action}`), editable at runtime
  in a role × module matrix that also lists every custom form. Role permissions are cached in memory and the cache is
  invalidated on change, so edits apply immediately.
* **Dashboard & report builder** — KPI cards, sales funnel, activity feed, pending tasks; reports with selectable
  columns, filters, sorting, grouping, Chart.js charts and Excel / PDF export.
* **Localization** — `IStringLocalizer`, `IViewLocalizer` (login page), DataAnnotations and FluentValidation messages;
  cookie-based language switcher; Jalali dates and Persian digits for `fa-IR`.

## Front-end

Bootstrap 5.3 (LTR and RTL builds), [htmx](https://htmx.org) for partial updates (lists, drawers, inline forms, Kanban,
reports), SignalR, Chart.js and jQuery Validation — all vendored under `wwwroot/lib`, so the app needs no CDN.
Custom CSS uses logical properties only, so one stylesheet serves both directions.

Reusable building blocks live in `Pages/Shared`: `_ChatPanelPartial`, `_TaskWidgetPartial`,
`_LanguageSwitcherPartial`, `_DynamicFormRendererPartial`, `_PagerPartial`, … plus the ViewComponents `NavMenu`,
`NotificationBell`, `EntityCollaboration` and `ActivityTimeline`.

## Configuration

| Setting (appsettings / environment variable) | Purpose | Default |
|---|---|---|
| `ConnectionStrings:DefaultConnection` | SQL Server connection | localhost dev instance |
| `Seed:AdminUserName`, `Seed:AdminPassword` | initial administrator | `admin` / `Admin@12345` |
| `Seed:DemoData`, `Seed:DemoPassword` | demo data and demo users | `true` / `Demo@12345` |
| `Seed:ApplyMigrations` | migrate the database on start-up | `true` |
| `Localization:DefaultCulture`, `Localization:SupportedCultures` | UI languages | `en-US`; `en-US`, `fa-IR` |
| `Regional:TimeZone` | time zone for displaying / reading dates | `Asia/Tehran` |
| `Regional:CurrencyFormatEn` / `CurrencyFormatFa` / `CurrencyDecimals` | currency display | `${0}` / `{0} دلار` / `0` |
| `Reminders:PollSeconds` | reminder worker interval | `30` |
| `Storage:Path`, `Storage:MaxFileBytes` | upload folder and size limit | `App_Data/uploads`, 10 MB |
| `DataProtection:KeysPath` | key ring location (keeps sign-ins across restarts) | `App_Data/keys` |

With Docker, use the variables in `.env.example`. **Change the default passwords before exposing the app**, and put it
behind an HTTPS reverse proxy (forwarded headers are honoured outside Development).

### Adding a language

1. Add the culture to `Localization:SupportedCultures`.
2. Add a column for it to `tools/i18n/*.tsv`, extend `tools/i18n/generate_resx.py` and run it to produce
   `Resources/SharedResource.{culture}.resx`.
3. Texts stored in the database (`LocalizedText`: form labels, stage and category names) currently carry English and
   Persian; add a property there for further languages.

UI texts are edited in `tools/i18n/translations.tsv` (key, Persian, optional English) and compiled to `.resx` with
`python3 tools/i18n/generate_resx.py`.

## Known limitations

* Date inputs use the browser's native (Gregorian) picker in both languages; dates are *displayed* in Jalali for `fa-IR`.
* Error messages produced by ASP.NET Core Identity (password policy, duplicate user name) are shown in English.
* Reports are run on demand; saving report definitions is not implemented.
* Uploaded files can be downloaded by any signed-in user who has the (unguessable) link.
* PDF export uses QuestPDF under its Community license — check <https://www.questpdf.com/license/> for commercial use.
* There is no automated test project yet.

---

<sub>Original repository notes: hi hello this is my firt repo · 1-is this hello · 2-are you sahre · 3-in khat be yadet ezafe mikonam</sub>
