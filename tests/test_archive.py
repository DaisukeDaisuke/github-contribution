import datetime as dt
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import urllib.error
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import generate
import publish
import render_report
import render_dialog


def sample_days():
    # A run crosses the year boundary; a zero separates it from another run.
    start = dt.date(2025,1,1)
    result=[]
    for i in range(372):
        date=start+dt.timedelta(days=i)
        count={
            '2025-12-29':2,'2025-12-30':3,'2025-12-31':5,
            '2026-01-01':7,'2026-01-02':11,'2026-01-04':13,
        }.get(date.isoformat(),0)
        result.append({'date':date.isoformat(),'count':count,'level':4 if count else 0})
    return result


def meta():
    return {'user':'Example','profileUrl':'https://github.com/Example','accountCreatedAt':'2025-01-03T12:00:00Z','dataFetchedAt':'2026-01-07T03:00:00Z','sourceName':'Test fixture','sourceUrl':'https://api.github.com/graphql','sourceType':'test','dataApiRequests':0}


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        generate._last_request_finished=None

    def test_date_coverage_rejects_missing_or_duplicate_days(self):
        days=sample_days()
        generate.validate_days(days,2025,dt.date(2026,1,7))
        with self.assertRaises(ValueError):generate.validate_days(days[:-1],2025,dt.date(2026,1,7))
        with self.assertRaises(ValueError):generate.validate_days(days+[days[0]],2025,dt.date(2026,1,7))

    def test_totals_rates_cross_year_streak_and_ytd_comparison(self):
        report=generate.build_report(sample_days(),meta(),2025,dt.date(2026,1,7))
        self.assertEqual(report['summary']['total'],41)
        self.assertEqual(report['summary']['activeDays'],6)
        self.assertEqual(report['summary']['eligibleDays'],370)
        self.assertEqual(report['summary']['longestStreak'],{'days':5,'start':'2025-12-29','end':'2026-01-02'})
        self.assertEqual(report['years'][0]['longestStreak']['days'],3)
        self.assertEqual(report['years'][1]['total'],31)
        self.assertEqual(report['years'][1]['comparisonPreviousTotal'],0)
        self.assertIsNone(report['years'][1]['comparisonChangePercent'])

    def test_only_missing_pre_account_days_may_be_filled(self):
        entries=[{'date':'2026-01-03','count':2,'level':1},{'date':'2026-01-04','count':0,'level':0}]
        result=generate.validate_days(entries,2026,dt.date(2026,1,4),'2026-01-03')
        self.assertEqual([d['count'] for d in result],[0,0,2,0])
        with self.assertRaises(ValueError):generate.validate_days(entries[:1],2026,dt.date(2026,1,4),'2026-01-03')

    def test_graphql_fetches_one_year_per_request_in_order(self):
        days=sample_days()
        responses=[]
        for index,year in enumerate([2025,2026]):
            user={'login':'Example','url':'https://github.com/Example','createdAt':meta()['accountCreatedAt']}
            selected=[d for d in days if d['date'].startswith(str(year))]
            user['contributionsCollection']={'contributionCalendar':{'totalContributions':sum(d['count'] for d in selected),'weeks':[{'contributionDays':[{'date':d['date'],'contributionCount':d['count'],'contributionLevel':'FOURTH_QUARTILE' if d['count'] else 'NONE'} for d in selected]}]}}
            responses.append(({'data':{'user':user,'rateLimit':{'cost':1,'limit':1000,'remaining':999-index,'resetAt':'2026-01-07T04:00:00Z'}}},{}))
        with patch.object(generate,'request_json',side_effect=responses) as request:
            actual,metadata,_=generate.fetch_graphql('Example',2025,dt.date(2026,1,7),'test-token')
        self.assertEqual(request.call_count,2)
        first=request.call_args_list[0].kwargs['body']['query']
        second=request.call_args_list[1].kwargs['body']['query']
        self.assertIn('2025-01-01',first);self.assertNotIn('2026-01-01',first)
        self.assertIn('2026-01-01',second)
        self.assertEqual(first.count('contributionsCollection('),1)
        self.assertIn('rateLimit',first)
        self.assertEqual(actual,days)
        self.assertEqual(metadata['rateLimit']['remaining'],998)
        self.assertEqual(metadata['dataApiRequests'],2)

    def test_waits_1_2_seconds_after_previous_request_completion(self):
        response=MagicMock()
        response.__enter__.return_value=response
        response.read.return_value=b'{}'
        response.headers={}
        with patch.object(generate.urllib.request,'urlopen',return_value=response) as request, patch.object(generate.time,'monotonic',return_value=100.0), patch.object(generate.time,'sleep') as sleep:
            generate.request_json('https://api.github.com/graphql',body={})
            generate.request_json('https://api.github.com/graphql',body={})
        self.assertEqual(request.call_count,2)
        sleep.assert_called_once_with(1.2)

    def test_rate_limit_stops_after_one_attempt(self):
        error=urllib.error.HTTPError('https://api.github.com/graphql',429,'Too many requests',{'Retry-After':'60'},None)
        with patch.object(generate.urllib.request,'urlopen',side_effect=error) as request:
            with self.assertRaisesRegex(RuntimeError,'without retry'):generate.request_json('https://api.github.com/graphql',token='test-token',body={})
        self.assertEqual(request.call_count,1)
        with patch.object(generate,'request_json',return_value=({'errors':[{'message':'API rate limit exceeded'}]},{})) as request:
            with self.assertRaisesRegex(RuntimeError,'without retry or fallback'):generate.fetch_graphql('Example',2025,dt.date(2026,1,7),'test-token')
        self.assertEqual(request.call_count,1)

    def test_all_years_share_one_continuous_grid(self):
        report=generate.build_report(sample_days(),meta(),2025,dt.date(2026,1,7))
        svg=render_report.render_svg(report)
        root=ET.fromstring(svg)
        cells=[node for node in root.iter() if 'data-date' in node.attrib]
        self.assertEqual(len(cells),372)
        self.assertEqual(sum(int(c.attrib['data-count']) for c in cells),41)
        self.assertFalse(any(c.attrib['data-date']>'2026-01-07' for c in cells))
        grids=[g for g in root.iter() if g.attrib.get('id')=='contribution-grid']
        self.assertEqual(len(grids),1)
        self.assertEqual(len(list(grids[0])),372)
        by_date={cell.attrib['data-date']:cell for cell in cells}
        december=by_date['2025-12-31'].attrib
        january=by_date['2026-01-01'].attrib
        self.assertEqual(december['x'],january['x'])
        self.assertEqual(int(january['y'])-int(december['y']),render_report.STEP)
        labels=[node for node in root.iter() if 'data-year' in node.attrib]
        self.assertEqual([node.text for node in labels],['2026','2025'])
        self.assertLess(float(labels[0].attrib['y']),float(labels[1].attrib['y']))
        self.assertLess(int(january['y']),int(by_date['2025-01-01'].attrib['y']))
        # A band moves as a unit: weeks still run left to right, Sunday to Saturday.
        self.assertLess(int(by_date['2026-01-01'].attrib['x']),int(by_date['2026-01-04'].attrib['x']))
        self.assertEqual(int(by_date['2026-01-05'].attrib['y'])-int(by_date['2026-01-04'].attrib['y']),render_report.STEP)
        self.assertTrue(all(float(node.attrib['x'])<min(float(c.attrib['x']) for c in cells) for node in labels))
        weekdays=[node for node in root.iter() if 'data-weekday' in node.attrib]
        self.assertTrue(weekdays)
        self.assertTrue(all(float(node.attrib['x'])>max(float(c.attrib['x']) for c in cells) for node in weekdays))
        page=render_report.render_html(report)
        self.assertNotIn('DaisukeDaisuke',page)
        self.assertIn('min-width:0',page)
        self.assertNotIn('year-card',page)
        self.assertNotIn('集計条件',page)
        self.assertNotIn('<footer',page)

    def test_offline_outputs_and_template_embed_url(self):
        report=generate.build_report(sample_days(),meta(),2025,dt.date(2026,1,7))
        with tempfile.TemporaryDirectory() as temp:
            snippet=generate.write_outputs(report,{'fixture':True},Path(temp),'TemplateOwner/reusable-map','contribution-graphs')
            self.assertIn('TemplateOwner/reusable-map/contribution-graphs/profile-dark3.webp#gh-dark-mode-only',snippet)
            self.assertIn('TemplateOwner/reusable-map/contribution-graphs/profile-light3.webp#gh-light-mode-only',snippet)
            self.assertIn(' \\\n',snippet)
            self.assertEqual(len((Path(temp)/'daily.csv').read_text(encoding='utf-8').splitlines()),373)
            data=json.loads((Path(temp)/'data.json').read_text(encoding='utf-8'))
            self.assertEqual(data['summary']['total'],41)
            self.assertTrue((Path(temp)/'profile-dark.svg').is_file())
            self.assertTrue((Path(temp)/'profile-light.svg').is_file())
            self.assertIn('data-theme="dark"',(Path(temp)/'profile-dark.html').read_text(encoding='utf-8'))
            self.assertTrue((Path(temp)/'profile-dark3.svg').is_file())
            self.assertIn('![profile](profile-dark3.webp#gh-dark-mode-only)',(Path(temp)/'README.md').read_text(encoding='utf-8'))

    def test_preview_clips_and_fades_without_moving_calendar_cells(self):
        report=generate.build_report(sample_days(),meta(),2025,dt.date(2026,1,7))
        ns={'s':'http://www.w3.org/2000/svg'}
        for theme in ['light','dark']:
            full=ET.fromstring(render_report.render_svg(report,theme))
            preview=ET.fromstring(render_report.render_preview_svg(report,theme,max_height=120,fade_height=30))
            self.assertEqual(preview.attrib['height'],'120')
            self.assertEqual(preview.attrib['viewBox'],'0 0 800 120')
            self.assertEqual(preview.attrib['data-fade-start'],'90')
            gradient=preview.find('.//s:linearGradient',ns)
            self.assertEqual(gradient.attrib['y1'],'90')
            self.assertEqual(gradient.attrib['y2'],'119')
            a={n.attrib['data-date']:n.attrib for n in full.iter() if 'data-date' in n.attrib}
            b={n.attrib['data-date']:n.attrib for n in preview.iter() if 'data-date' in n.attrib}
            self.assertEqual(a,b)

    def test_dialog_is_standalone_and_embeds_both_full_and_preview_images(self):
        import base64
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            (directory/'data.json').write_text(json.dumps({'metadata':{'user':'Example & Test'}}),encoding='utf-8')
            files=['profile-dark3.webp','profile-light3.webp','profile-dark.webp','profile-light.webp']
            for name in files:(directory/name).write_bytes(('test '+name).encode('ascii'))
            target=render_dialog.render_dialog(directory)
            content=target.read_text(encoding='utf-8')
            self.assertIn('<dialog id="profile-dialog"',content)
            self.assertIn('Example &amp; Test',content)
            self.assertNotIn('__DARK_',content)
            for name in files:
                encoded=base64.b64encode(('test '+name).encode('ascii')).decode('ascii')
                self.assertIn('data:image/webp;base64,'+encoded,content)

    def test_dark_and_light_preserve_identical_grid_geometry_and_data(self):
        report=generate.build_report(sample_days(),meta(),2025,dt.date(2026,1,7))
        light=ET.fromstring(render_report.render_svg(report))
        dark=ET.fromstring(render_report.render_svg(report,theme='dark'))
        left={n.attrib['data-date']:n.attrib for n in light.iter() if 'data-date' in n.attrib}
        right={n.attrib['data-date']:n.attrib for n in dark.iter() if 'data-date' in n.attrib}
        self.assertEqual(left.keys(),right.keys())
        for date in left:
            for key in ['x','y','width','height','rx','data-count','data-level']:
                self.assertEqual(left[date][key],right[date][key])
            self.assertEqual(right[date]['fill'],render_report.THEMES['dark']['palette'][int(right[date]['data-level'])])
        light_labels=[(n.attrib['x'],n.attrib['y'],n.text) for n in light.iter() if 'data-year' in n.attrib or 'data-weekday' in n.attrib]
        dark_labels=[(n.attrib['x'],n.attrib['y'],n.text) for n in dark.iter() if 'data-year' in n.attrib or 'data-weekday' in n.attrib]
        self.assertEqual(light_labels,dark_labels)
        self.assertEqual(light.attrib['viewBox'],dark.attrib['viewBox'])

    def test_publisher_changes_only_dedicated_branch_and_keeps_history(self):
        def git(*args,cwd):return subprocess.run(['git',*args],cwd=cwd,check=True,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE).stdout.strip()
        with tempfile.TemporaryDirectory() as temp:
            base=Path(temp);repo=base/'repo';remote=base/'remote.git';out=base/'out'
            repo.mkdir();out.mkdir()
            git('init','--bare',str(remote),cwd=base)
            git('init','-b','main',cwd=repo)
            git('config','user.name','Test',cwd=repo);git('config','user.email','test@example.invalid',cwd=repo)
            (repo/'README.md').write_text('Template source README\n',encoding='utf-8')
            (repo/'source-only.txt').write_text('source\n',encoding='utf-8')
            git('add','.',cwd=repo);git('commit','-m','Initial template',cwd=repo)
            git('remote','add','origin',str(remote),cwd=repo);git('push','origin','main',cwd=repo)
            original=git('rev-parse','HEAD',cwd=repo)
            for name in ['contributions.svg','index.html','data.json','daily.csv','README.md','embed.md']:(out/name).write_text('first\n',encoding='utf-8')
            publish.publish(out,repo=repo)
            first=git('ls-remote','origin','refs/heads/contribution-graphs',cwd=repo).split()[0]
            self.assertEqual(git('rev-parse','HEAD',cwd=repo),original)
            self.assertEqual((repo/'README.md').read_text(encoding='utf-8'),'Template source README\n')
            self.assertNotIn('source-only.txt',git('ls-tree','--name-only',first,cwd=repo))
            (out/'contributions.svg').write_text('updated\n',encoding='utf-8')
            publish.publish(out,repo=repo)
            second=git('ls-remote','origin','refs/heads/contribution-graphs',cwd=repo).split()[0]
            self.assertNotEqual(first,second)
            self.assertEqual(git('rev-parse',second+'^',cwd=repo),first)
            self.assertEqual(git('rev-parse','HEAD',cwd=repo),original)
            with self.assertRaises(ValueError):publish.publish(out,branch='main',repo=repo)


if __name__=='__main__':unittest.main()
