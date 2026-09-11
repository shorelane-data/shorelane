# Ad-hoc analyst queries

Hand-written BigQuery SQL an analyst at Shorelane might actually run: questions the
dashboards don't answer directly. Each file states the question and the rule it
relies on. All run against `nodal-shorelane.shorelane` (the dbt marts); a few
deliberately compare a mart to staging to show what the mart's rule is worth.

Run one with:

```
bq query --project_id=nodal-shorelane --use_legacy_sql=false < bi/ad-hoc/01_five_revenues_by_quarter.sql
```

Use explicit, fully elapsed date bounds: the warehouse is drip-fed daily, so
anything relative to "today" moves.
