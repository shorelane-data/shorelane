# LookML is an authored context artifact only. We do not run a Looker instance:
# Looker core is an enterprise product, and this file exists so context
# consumers can inspect the safe semantic contract without a deployment.
#
# Deliberately expose only the one-row customer dimension and the aggregated
# identity-quality mart. Do not expose or create an Explore over the long
# int_customer_identity bridge; its multiple aliases per app customer can fan out
# facts. Dashboard rendering belongs in Looker Studio or bi/plotly.

view: dim_customers {
  sql_table_name: shorelane.dim_customers ;;

  dimension: app_db_customer_id {
    type: string
    primary_key: yes
    sql: ${TABLE}.app_db_customer_id ;;
    description: "One row per canonical app ID. This is the safe customer grain."
  }

  dimension: has_order {
    type: yesno
    sql: ${TABLE}.has_order ;;
    description: "Filter has_order = true for the canonical business customer count."
  }

  measure: ordered_canonical_customers {
    type: count_distinct
    sql: ${app_db_customer_id} ;;
    filters: [has_order: "yes"]
    description: "Canonical app customers with at least one order, counted once."
  }
}

view: fct_identity_resolution_quality {
  sql_table_name: shorelane.fct_identity_resolution_quality ;;

  dimension: source_system {
    type: string
    sql: ${TABLE}.source_system ;;
    description: "Source namespace; identity IDs are never compared without it."
  }

  measure: observed_source_ids {
    type: sum
    sql: ${TABLE}.observed_id_count ;;
  }

  measure: resolved_source_ids {
    type: sum
    sql: ${TABLE}.resolved_id_count ;;
  }

  measure: unresolved_source_ids {
    type: sum
    sql: ${TABLE}.unresolved_id_count ;;
  }

  measure: resolution_null_rate {
    type: number
    sql: 1.0 * ${unresolved_source_ids} / NULLIF(${observed_source_ids}, 0) ;;
    value_format_name: percent_2
    description: "Unresolved source IDs divided by observed source IDs at the snapshot."
  }
}
