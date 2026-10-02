{#
  Guard the benchmark boundary in both directions, before anything is built:
    - the bench target must read the frozen raw snapshot OF THE SAME VERSION
      (shorelane_bench_v1 <- shorelane_raw_bench_v1), never the live shorelane_raw;
    - every other target must never read a bench snapshot.
  A mismatch would silently build a benchmark from moving data, or a production
  mart from a frozen one.
#}
{% macro assert_raw_dataset_matches_target() %}
  {%- set raw = var('raw_dataset') -%}
  {%- set bench_raw_prefix = 'shorelane_raw_bench_' -%}
  {%- if target.name == 'bench' -%}
    {%- if not raw.startswith(bench_raw_prefix) -%}
      {{ exceptions.raise_compiler_error(
          "bench target must read a frozen snapshot (shorelane_raw_bench_<v>), got raw_dataset=" ~ raw) }}
    {%- endif -%}
    {%- set expected = 'shorelane_bench_' ~ raw[bench_raw_prefix | length:] -%}
    {%- if target.dataset != expected -%}
      {{ exceptions.raise_compiler_error(
          "bench target dataset " ~ target.dataset ~ " does not match raw snapshot " ~ raw
          ~ " (expected " ~ expected ~ ")") }}
    {%- endif -%}
  {%- elif raw.startswith(bench_raw_prefix) -%}
    {{ exceptions.raise_compiler_error(
        "target " ~ target.name ~ " must not read a bench snapshot (raw_dataset=" ~ raw ~ ")") }}
  {%- endif -%}
{% endmacro %}
