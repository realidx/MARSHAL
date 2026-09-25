import json,glob,collections,pathlib,tarfile,tempfile
archive=pathlib.Path(__file__).resolve().parents[1]/'raw_runs.tar.gz'
scratch=tempfile.TemporaryDirectory(prefix='diagnostic-v7-audit-')
with tarfile.open(archive) as tar:tar.extractall(scratch.name,filter='data')
out=pathlib.Path('new/diagnostic_v7_results_20260926/audit');cases={c['id']:c for c in json.load(open('new/diagnostic_v7/cases.json'))};runs={}
for p in glob.glob(scratch.name+'/runs/diagnostic_v7/*/structure_v7/results.json'):
 name='Q0' if 'q0-base' in p else 'D';rs=json.load(open(p));calls=[json.loads(l) for l in open(p.replace('results.json','calls.jsonl'))];ci={(r['case_id'],r['condition']):r for r in calls};runs[name]=(rs,ci)
 for cond in ('O','P_gold','P_model'):
  counts=collections.Counter();wrong=collections.Counter()
  for r in rs:
   call=ci[r['case_id'],cond];tools=call['completion']['raw_message'].get('tool_calls',[]);a=tools[0]['function']['name'] if tools else 'INVALID';counts[a]+=1
   if not r[cond]['correct']:wrong[a]+=1
  print(name,cond,counts,'wrong',wrong)
 print(name,'B set exact',sum(set(r['B']['prediction']['possible_preferences'])==set(r['B']['gold']['possible_preferences']) for r in rs),'favoredexact',sum(r['B']['prediction']['favored']==r['B']['gold']['favored'] for r in rs))
 print(name,'BwrongOcorrect',sum(not r['B']['correct'] and r['O']['correct'] for r in rs))
 bad=[r for r in rs if r['O']['correct'] and not r['P_gold']['correct']]
 print(name,'O+P-',len(bad),collections.Counter(r['stratum'] for r in bad))
 text=[]
 for r in rs:
  c=cases[r['case_id']];text.append('\n### '+r['case_id']+' '+r['stratum']+' '+str({k:r[k]['correct'] for k in ['B','O','P_gold','P_model']}))
  for cond in ('B','O','P_gold','P_model'):
   call=ci[r['case_id'],cond];m=call['completion']['raw_message'];text.append('\n'+cond+' '+json.dumps(m.get('tool_calls'))+'\n'+m.get('content',''))
 (out/(name+'_all_calls.md')).write_text('\n'.join(text))
a={r['case_id']:r for r in runs['Q0'][0]};b={r['case_id']:r for r in runs['D'][0]}
for cond in ('B','O','P_gold','P_model'):
 loss=[i for i in a if a[i][cond]['correct'] and not b[i][cond]['correct']];gain=[i for i in a if not a[i][cond]['correct'] and b[i][cond]['correct']];print(cond,'LOSS',loss,'GAIN',gain)
(out/'paired.json').write_text(json.dumps({i:{'Q0':a[i],'D':b[i]} for i in a},indent=2))
