select *
from {{ ref('fct_identity_resolution_quality') }}
where resolution_null_rate < 0
   or resolution_null_rate > 1
   or abs(
       resolution_null_rate
       - case
           when observed_id_count = 0 then 0.0
           else 1.0 * unresolved_id_count / observed_id_count
         end
   ) > 0.000001
