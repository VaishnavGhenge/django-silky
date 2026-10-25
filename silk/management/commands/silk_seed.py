"""Generate consistent, synthetic traffic for the example blind catalog.

    DB_ENGINE=sqlite3 .venv/bin/python project/manage.py silk_seed --clear --example-data

The records simulate production traffic; they do not replay HTTP requests.
"""

import ast
import json
import random
import sys
from datetime import timedelta
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from silk import models


CATALOG = [
    {"name": f"{colour} {style} Blind", "child_safe": safe}
    for style, safe in [("Blackout Roller", True), ("Linen Roman", False),
                        ("Cordless Venetian", True), ("Solar Screen", True)]
    for colour in ["Chalk", "Oatmeal", "Slate", "Sand", "Ivory", "Charcoal"]
]

_APP_VIEWS = Path(__file__).resolve().parents[3] / "project" / "example_app" / "views.py"
_SITE_PACKAGES = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
_SELECT = 'SELECT "example_app_blind"."id", "example_app_blind"."photo", "example_app_blind"."name", "example_app_blind"."child_safe" FROM "example_app_blind"'
_COUNT = 'SELECT COUNT(*) AS "__count" FROM "example_app_blind"'


def _source_frames():
    """Resolve source locations so clicking a sample traceback opens the right line."""
    if not _APP_VIEWS.exists():
        return {}
    source = _APP_VIEWS.read_text().splitlines()
    result = {}
    for node in ast.walk(ast.parse("\n".join(source))):
        if isinstance(node, ast.FunctionDef):
            for child in ast.walk(node):
                if isinstance(child, (ast.Assign, ast.Return)):
                    result.setdefault(node.name, []).append((child.lineno, source[child.lineno - 1].strip()))
    return result


def _location(frames, function, snippet):
    candidates = frames.get(function, [])
    return next(((line, code) for line, code in candidates if snippet in code),
                candidates[0] if candidates else (1, ""))


def _traceback(frames, function, snippet):
    line, code = _location(frames, function, snippet)
    stack = [
        (_SITE_PACKAGES / "django/core/handlers/base.py", 197, "_get_response",
         "response = wrapped_callback(request, *callback_args, **callback_kwargs)"),
        (_APP_VIEWS, line, function, code),
        (_SITE_PACKAGES / "django/db/models/sql/compiler.py", 1547, "execute_sql",
         "cursor.execute(sql, params)"),
    ]
    return "\n".join(f'  File "{path}", line {lineno}, in {func}\n    {text}'
                     for path, lineno, func, text in stack)


def _quote(value):
    return "'" + value.replace("'", "''") + "'"


def _scenario(kind, catalog, rng):
    """Keep routing, payloads and interpolated SQL together for each endpoint."""
    item = rng.choice(catalog)
    data = {"method": "GET", "path": "/example_app/api/blinds/", "params": {},
            "function": "api_blind_list", "status": 200, "body": None,
            "content_type": "application/json", "queries": []}
    if kind in ("list", "search"):
        results = catalog
        sql = _SELECT
        if kind == "search":
            term = rng.choice(["Roller", "Roman", "Slate", "Cordless"])
            data["params"] = {"search": [term], "child_safe": ["true"]}
            results = [b for b in catalog if term.lower() in b["name"].lower() and b["child_safe"]]
            sql += f' WHERE "example_app_blind"."name" LIKE {_quote("%" + term + "%")} ESCAPE '\
                   "'\\' AND \"example_app_blind\".\"child_safe\""
        data["response"] = {"results": results, "count": len(results)}
        data["queries"] = [(sql, "for b in qs")]
    elif kind in ("detail", "missing"):
        pk = item["id"] if kind == "detail" else max(b["id"] for b in catalog) + rng.randint(100, 1000)
        data.update(path=f"/example_app/api/blinds/{pk}/", function="api_blind_detail")
        data["queries"] = [(f'{_SELECT} WHERE "example_app_blind"."id" = {pk} LIMIT 21', "get_object_or_404")]
        data["response"] = item
        if kind == "missing":
            data.update(status=404, content_type="text/html",
                        response="<!doctype html><html><head><title>Not Found</title></head>"
                                 "<body><h1>Not Found</h1><p>The requested resource was not found.</p></body></html>")
    elif kind in ("create", "invalid"):
        data.update(method="POST", path="/example_app/api/blinds/create/", function="api_blind_create")
        if kind == "invalid":
            data.update(body={"name": "", "child_safe": True}, status=400,
                        response={"error": "name is required"})
        else:
            # A distinct made-to-measure name avoids the model's unique-name constraint.
            name = f'{item["name"]} — Custom {rng.randrange(100000, 999999)}'
            pk = max(b["id"] for b in catalog) + 1
            created = {"id": pk, "name": name, "child_safe": item["child_safe"]}
            catalog.append(created)
            data.update(body={"name": name, "child_safe": item["child_safe"]}, status=201, response=created)
            sql = ('INSERT INTO "example_app_blind" ("photo", "name", "child_safe") '
                   f'VALUES (\'\', {_quote(name)}, {str(item["child_safe"]).upper()}) RETURNING "example_app_blind"."id"')
            data["queries"] = [(sql, "objects.create")]
    elif kind == "stats":
        safe = sum(b["child_safe"] for b in catalog)
        data.update(path="/example_app/api/blinds/stats/", function="api_blind_stats",
                    response={"total": len(catalog), "child_safe": safe, "unsafe": len(catalog) - safe,
                              "names": [b["name"] for b in catalog]})
        data["queries"] = [(_COUNT, "objects.count"),
                           (_COUNT + ' WHERE "example_app_blind"."child_safe"', "child_safe=True"),
                           (_COUNT + ' WHERE NOT "example_app_blind"."child_safe"', "child_safe=False"),
                           (_SELECT, "objects.all")]
        data["queries"] += [
            (f'SELECT "example_app_blind"."name" FROM "example_app_blind" WHERE "example_app_blind"."id" = {b["id"]} ORDER BY "example_app_blind"."id" ASC LIMIT 1', "values_list")
            for b in catalog
        ]
    else:  # The example homepage intentionally sleeps for 1.345 seconds.
        data.update(path="/example_app/", function="index", content_type="text/html",
                    response="<!doctype html><html><head><title>Blind catalog</title></head>"
                             "<body><h1>Made-to-measure blinds</h1></body></html>",
                    queries=[(_SELECT, "render(request")])
    return data


def _make_request(scenario, start, rng, frames):
    function = scenario["function"]
    is_home = function == "index"
    is_stats = function == "api_blind_stats"
    duration = rng.uniform(1355, 1650) if is_home else rng.lognormvariate(3.5, 0.55)
    if is_stats:
        duration += len(scenario["queries"]) * rng.uniform(2, 5)
    # An occasional slow DB/worker produces a long tail, as in real traffic.
    if not is_home and rng.random() < 0.02:
        duration += rng.uniform(400, 1400)
    end = start + timedelta(milliseconds=duration)
    body = json.dumps(scenario["body"]) if scenario["body"] is not None else ""
    headers = {"accept": scenario["content_type"], "host": "catalog.example.test",
               "user-agent": rng.choice(["Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
                                         "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"])}
    if body:
        headers["content-type"] = "application/json"
        headers["content-length"] = str(len(body.encode()))
    req = models.Request.objects.create(
        method=scenario["method"], path=scenario["path"], query_params=json.dumps(scenario["params"]),
        start_time=start, end_time=end, view_name=f"example_app:{function}",
        encoded_headers=json.dumps(headers), body=body, raw_body=body,
        meta_time=rng.uniform(0.2, 1.5), meta_num_queries=3,
        meta_time_spent_queries=rng.uniform(0.1, 0.8),
    )
    response_body = json.dumps(scenario["response"]) if scenario["content_type"] == "application/json" else scenario["response"]
    models.Response.objects.create(
        request=req, status_code=scenario["status"], body=response_body, raw_body=response_body,
        encoded_headers=json.dumps({"content-type": scenario["content_type"],
                                    "content-length": str(len(response_body.encode()))}),
    )
    sqls = scenario["queries"]
    queries = []
    # Execute sequentially inside the request, leaving time for application work.
    if sqls:
        budget = duration * (0.03 if is_home else rng.uniform(0.25, 0.65))
        weights = [rng.uniform(0.5, 2) for _ in sqls]
        total_weight = sum(weights)
        cursor = start + timedelta(milliseconds=duration * 0.08)
        for (sql, snippet), weight in zip(sqls, weights):
            finish = cursor + timedelta(milliseconds=budget * weight / total_weight)
            queries.append(models.SQLQuery.objects.create(
                request=req, query=sql, start_time=cursor, end_time=finish,
                traceback=_traceback(frames, function, snippet),
            ))
            cursor = finish + timedelta(milliseconds=duration * 0.05 / len(sqls))
    if is_home or is_stats or rng.random() < 0.12:
        profile_start = start + timedelta(milliseconds=duration * 0.04)
        profile_end = end - timedelta(milliseconds=duration * 0.04)
        line, _ = _location(frames, function, "")
        profile = models.Profile.objects.create(
            request=req, name="Catalog statistics" if is_stats else "Render catalog" if is_home else "Catalog lookup",
            file_path=str(_APP_VIEWS), line_num=line, func_name=function,
            start_time=profile_start, end_time=profile_end,
        )
        profile.queries.set(queries)
    if is_home:
        # Synthetic pstats text with the same total duration as this recording.
        seconds = duration / 1000
        line, _ = _location(frames, "index", "render(request")
        req.pyprofile = (
            f"         64 function calls in {seconds:.3f} seconds\n\n"
            "   Ordered by: cumulative time\n\n"
            "   ncalls  tottime  percall  cumtime  percall filename:lineno(function)\n"
            f"        1    0.001    0.001    {seconds:.3f}    {seconds:.3f} {_APP_VIEWS}:{line}(index)\n"
            "        1    1.345    1.345    1.345    1.345 {built-in method time.sleep}\n"
        )
        req.save(update_fields=["pyprofile"])
    return req


class Command(BaseCommand):
    help = "Seed consistent, synthetic production-style traffic for the example catalog."

    def add_arguments(self, parser):
        parser.add_argument("--requests", type=int, default=200, help="Requests to create (default: 200)")
        parser.add_argument("--days", type=int, default=7, help="Past days to cover (default: 7)")
        parser.add_argument("--clear", action="store_true", help="Replace existing Silk profiling records")
        parser.add_argument("--seed", type=int, help="Random seed for repeatable traffic")
        parser.add_argument("--example-data", action="store_true", help="Also populate the example app's blind catalog")

    @transaction.atomic
    def handle(self, *args, **options):
        count, days = options["requests"], options["days"]
        if count < 0:
            raise CommandError("--requests must be zero or greater")
        if days < 1:
            raise CommandError("--days must be at least 1")
        catalog = [{"id": i, **item} for i, item in enumerate(CATALOG, 1)]
        if options["example_data"]:
            if not apps.is_installed("example_app"):
                raise CommandError("--example-data requires the example_app application")
            blind_model = apps.get_model("example_app", "Blind")
            for item in CATALOG:
                blind_model.objects.get_or_create(name=item["name"], defaults={"child_safe": item["child_safe"]})
            catalog = list(blind_model.objects.order_by("pk").values("id", "name", "child_safe"))
        if options["clear"]:
            self.stdout.write("Clearing existing Silk profiling records…")
            models.Profile.objects.all().delete()
            models.SQLQuery.objects.all().delete()
            models.Request.objects.all().delete()
        # Preserve compatibility with callers using random.seed(), such as benchmarks.
        rng = random.Random(options["seed"]) if options["seed"] is not None else random
        now = timezone.now()
        window_start = now - timedelta(days=days)
        frames = _source_frames()
        # Mostly reads and successful responses. Rare errors and expensive stats
        # leave enough examples to exercise the profiler without dominating it.
        kinds = ["list", "search", "detail", "create", "invalid", "missing", "stats", "home"]
        weights = [30, 24, 29, 5, 2, 3, 3, 4]
        # Sort chronologically so simulated creates affect only subsequent reads.
        starts = sorted(window_start + timedelta(seconds=rng.uniform(0, days * 86400 - 10))
                        for _ in range(count))
        for start in starts:
            kind = rng.choices(kinds, weights=weights)[0]
            scenario = _scenario(kind, catalog, rng)
            _make_request(scenario, start, rng, frames)
        self.stdout.write(self.style.SUCCESS(
            f"Created {count} requests across {days} days. "
            f"Database totals: {models.Request.objects.count()} requests, "
            f"{models.SQLQuery.objects.count()} SQL queries, {models.Profile.objects.count()} profiles."
        ))
