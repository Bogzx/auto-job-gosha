echo "=== sample of delivered jobs (title / company / location / source / score) ==="
docker exec gosha-postgres psql -U gosha -d gosha -c "
select left(j.title, 42) as title, left(j.company, 22) as company,
       left(j.location, 26) as location, j.source,
       round(uj.relevance_score::numeric, 2) as score
from user_jobs uj join jobs j on j.id = uj.job_id
where uj.delivered_at > now() - make_interval(hours => 3)
order by random() limit 25;"
echo "=== what the matched subscriptions asked for ==="
docker exec gosha-postgres psql -U gosha -d gosha -c "
select distinct s.keywords, s.locations, s.remote_ok
from user_jobs uj join subscriptions s on s.id = uj.subscription_id
where uj.delivered_at > now() - make_interval(hours => 3) limit 12;"
echo "=== sample delivered URLs ==="
docker exec gosha-postgres psql -U gosha -d gosha -t -A -c "
select j.url from user_jobs uj join jobs j on j.id = uj.job_id
where uj.delivered_at > now() - make_interval(hours => 3)
  and j.source in ('ejobs','bestjobs') order by random() limit 6;"
