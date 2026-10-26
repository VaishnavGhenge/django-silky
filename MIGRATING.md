# Migrating from django-silk to django-silky

## Upgrading to django-silky 1.7.0: one new migration

**What changed.** 1.7.0 rebuilds the interface and adds the SQL, Hotspots and Compare pages. To group queries by shape and by calling line in the database, migration `silk.0010_sqlquery_pattern_location` adds two columns to `silk_sqlquery` (`pattern_hash` and `code_location`), two composite indexes, and fills both columns for queries already recorded.

**What to do.** Run the migration after upgrading:

```bash
python manage.py migrate silk
```

The backfill reads every recorded query in batches of 2,000. It took about 10 s for 76,000 queries on SQLite; on a large table, run it when a short write lock on `silk_sqlquery` is acceptable, or clear old data first.

**Template overrides.** The old base templates and per-page assets are gone. If your project overrides any `silk/...` template, compare it against the new one. URL names and `SILKY_*` settings are unchanged.

## Upgrading to django-silky 1.2.0 — defaults are now secure

**What changed.** In earlier releases `SILKY_AUTHENTICATION` and `SILKY_AUTHORISATION` both defaulted to `False`, so anyone with network access to `/silk/` could read the full profiling UI. Starting with 1.2.0 both default to `True`, and the default `SILKY_PERMISSIONS` predicate requires `user.is_staff`.

**Who is affected.** Anyone who was relying on the unauthenticated `/silk/` UI — whether intentionally (internal dev server, air-gapped environment) or not.

**Symptom after upgrade.** Visiting `/silk/` as an anonymous user, or as a logged-in non-staff user, now returns `404 Not Found`. Logged-in staff users see the UI unchanged.

**Opting back in to the old behaviour.** Add to `settings.py`:

```python
SILKY_AUTHENTICATION = False
SILKY_AUTHORISATION = False
```

**Why 404 and not 403?** To reduce fingerprinting — a 404 doesn't reveal that silk is mounted. This is defense-in-depth; the real security is the auth check itself.

**Caveat: static-asset fingerprinting.** Static files under `/static/silk/…` are served by your static-file stack (nginx, whitenoise, etc.) and are not covered by silk's auth decorators. If you need full opacity, restrict that prefix at your edge.

---

## From django-silk to django-silky

`django-silky` is a **drop-in replacement** for `django-silk`. It uses the
same Django app label (`silk`) and carries upstream's migrations (0001 to
0009) unchanged. It adds one of its own, 0010, which adds two columns and two
indexes to `silk_sqlquery`. Switching does not drop or move any existing
table, and all recorded requests, SQL queries and profiles are kept.

---

## Compatibility matrix

| django-silk version | Compatible with django-silky? | Notes |
|---|---|---|
| 5.6.x (latest) | ✅ Yes | Run `migrate silk` (applies 0010) |
| 5.0 to 5.5 | ✅ Yes | Run `migrate silk` (applies 0009 if missing, then 0010) |
| < 5.0 | ✅ Yes | Run `migrate silk` (applies every missing migration) |

> **Baseline:** `django-silky` is synced with `django-silk` through 5.6.0 and
> its later master (commit `d273516`). Its schema is upstream's plus the two
> columns from migration 0010.

---

## Migration steps

### From django-silk 5.x (recommended path)

1. **Back up your database** (always a good idea before swapping packages):

   ```bash
   # PostgreSQL
   pg_dump -Fc mydb > silk_backup_$(date +%Y%m%d).dump

   # MySQL
   mysqldump mydb > silk_backup_$(date +%Y%m%d).sql

   # SQLite
   cp db.sqlite3 db.sqlite3.bak
   ```

2. **Swap the package** — uninstall the old, install the new:

   ```bash
   pip uninstall django-silk
   pip install django-silky
   ```

3. **Run the migrations.** django-silky keeps the app label (`silk`) and
   upstream's migration files, and adds 0010:

   ```bash
   python manage.py migrate silk
   ```

4. **No `settings.py` changes.** The app label stays `'silk'`:

   ```python
   # unchanged — this is correct for django-silky too
   INSTALLED_APPS = [
       ...
       'silk',
   ]
   ```

5. **Restart your server** and visit `/silk/` to verify the UI loads and
   your existing data is visible.

---

### From django-silk < 5.0

Same steps as above. django-silky carries the full set of upstream
migrations, so `migrate silk` applies whatever an older install is missing,
then 0010.

---

## What changes in the UI

Silk records the same data as django-silk. What you see differs:

- **Requests**: filter chips with counts, a top bar search, and a side panel that opens a request without leaving the list
- **Request detail**: an overview with the SQL versus Python split, N+1 and duplicate detection with a likely fix, and copyable curl and query-count tests
- **SQL and Hotspots** (new): queries grouped by shape, and lines of your code ranked by the database time they cause
- **Summary**: latency over time, the endpoints to fix first, and where the time goes
- **Profiling**: profiles grouped into code blocks, and cProfile output as a sortable function list
- **Compare** (new): two requests, or two time ranges
- **Settings**: theme and accent, editor links, and thresholds for slow requests and N+1

All configuration settings (`SILKY_*`) work as before.

---

## Rollback

If you need to revert to `django-silk`:

```bash
pip uninstall django-silky
pip install django-silk
```

The two columns added by migration 0010 have a database default, so
django-silk keeps recording after a downgrade even with them in place. To
remove them and return to upstream's schema, migrate back before swapping:

```bash
python manage.py migrate silk 0009
pip uninstall django-silky
pip install django-silk
```

---

## Verifying data retention

After switching, spot-check a few things in the `/silk/` UI:

- [ ] Requests table shows historical entries with correct timestamps
- [ ] Clicking a request opens its detail page (headers, body, SQL count)
- [ ] SQL tab lists queries for an existing request
- [ ] Profiling page shows any previously recorded profiles
- [ ] Summary page shows aggregate metrics from historical data

---

## Frequently asked questions

**Do I need to run `manage.py migrate` when switching?**
Yes, once: `python manage.py migrate silk` applies migration 0010, which
django-silk does not have.

**Does django-silky add new migrations?**
One so far: 0010 adds `pattern_hash` and `code_location` to `silk_sqlquery`,
with indexes, for the SQL and Hotspots pages. Any later ones will be listed
here.

**Can I use django-silky and django-silk at the same time?**
No — both install under the `silk` app label, so only one can be installed
in a given Python environment.

**Will my `SILKY_*` settings still work?**
Yes, all configuration options are unchanged. See the
[Configuration section in the README](README.md#configuration) for the full
list.
