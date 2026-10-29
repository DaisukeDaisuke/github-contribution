import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import activity


def response(next_page=False, repo_id='one'):
    return {'data': {'user': {
        'login': 'OtherUser', 'avatarUrl': 'https://avatars.githubusercontent.com/u/1',
        'followers': {'totalCount': 23}, 'following': {'totalCount': 7},
        'repositories': {'totalCount': 2 if next_page else 1,
            'pageInfo': {'hasNextPage': next_page, 'endCursor': repo_id},
            'nodes': [{'id': repo_id, 'isArchived': False, 'stargazerCount': 3,
                'forkCount': 2, 'releases': {'totalCount': 4},
                'languages': {'totalSize': 100,
                    'edges': [{'size': 80, 'node': {'name': 'Python', 'color': '#3572A5'}}]}}]}},
        **{key: {'issueCount': i+1} for i,key in enumerate(activity.FILTERS)},
        'rateLimit': {'remaining': 4000, 'cost': 1}}}


class ActivityTests(unittest.TestCase):
    def test_weekly_cache_isolates_user_and_reuses_avatar_next_week(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls, avatars = [], []
            def request(*args, **kwargs):
                calls.append(kwargs)
                return response(), {}
            def avatar(url):
                avatars.append(url)
                return 'data:image/png;base64,AA=='
            first = activity.collect('OtherUser', 'SECRET',tmp,'2031-01-01',request,avatar)
            self.assertEqual(first['languages'][1]['size'],20)
            self.assertEqual(activity.collect('otheruser','SECRET',tmp,'2031-01-04',request,avatar), first)
            self.assertEqual(len(calls),1)
            activity.collect('OtherUser','SECRET',tmp,'2031-01-06',request,avatar)
            self.assertEqual(len(calls),2)
            self.assertEqual(len(avatars),1)
            stored = (Path(tmp)/'public/otheruser/snapshot.json').read_text()
            self.assertNotIn('SECRET',stored)
            self.assertNotIn('repositories": {',stored)  # No raw repository nodes.
            with self.assertRaises(ValueError):
                activity.collect('../user','SECRET',tmp,'2031-01-06',request,avatar)
            with self.assertRaises(ValueError):
                activity.collect('DifferentUser','SECRET',tmp,'2031-01-06',request,avatar)

    def test_iso_week_year_boundary(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            def request(*args, **kwargs):
                calls.append(1)
                return response(), {}
            avatar=lambda _: 'data:image/png;base64,AA=='
            first=activity.collect('OtherUser','token',tmp,'2026-12-31',request,avatar)
            self.assertEqual(first['week'],'2026-W53')
            activity.collect('OtherUser','token',tmp,'2027-01-01',request,avatar)
            self.assertEqual(len(calls),1)
            updated=activity.collect('OtherUser','token',tmp,'2027-01-04',request,avatar)
            self.assertEqual(updated['week'],'2027-W01')
            self.assertEqual(len(calls),2)

    def test_pagination_and_budget_show_partial_coverage(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, 'MAX_PAGES', 2):
            calls=[]
            def request(*args,**kwargs):
                calls.append(kwargs)
                raw=response(True,str(len(calls)))
                raw['data']['user']['repositories']['totalCount']=300
                return raw,{}
            model=activity.collect('OtherUser','token',tmp,'2031-01-01',request,lambda _: 'data:image/png;base64,AA==')
            self.assertEqual(len(calls),2)
            self.assertIsNone(calls[0]['body']['variables']['cursor'])
            self.assertEqual(calls[1]['body']['variables']['cursor'],'1')
            self.assertNotIn('search(', calls[1]['body']['query'])
            self.assertTrue(model['partial'])
            self.assertEqual(model['sampled'],2)
            self.assertEqual(model['stars'],6)
            self.assertIn('PARTIAL SAMPLE',activity.render(model))

    def test_errors_do_not_write_cache_or_retry(self):
        for raw in [{'errors':[{'message':'rate limited'}]}, {'data':{'user':None}}]:
            with tempfile.TemporaryDirectory() as tmp:
                calls=[]
                def request(*args,**kwargs):
                    calls.append(1)
                    return raw,{}
                with self.assertRaises((RuntimeError,ValueError)):
                    activity.collect('OtherUser','token',tmp,'2031-01-01',request)
                self.assertEqual(len(calls),1)
                self.assertFalse(list(Path(tmp).rglob('*.json')))

    def test_images_are_independent_and_only_images_are_published(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            model=activity.collect('OtherUser','token',root/'cache','2031-01-01',
                                   lambda *a,**k:(response(),{}),lambda _:'data:image/png;base64,AA==')
            dist=root/'dist';dist.mkdir()
            for stem in ('profile-dark','profile-light','profile-dark3','profile-light3'):
                (dist/(stem+'.svg')).write_text('unchanged original')
            activity.write_outputs(model,dist,'Someone/map','images')
            for theme in ('dark','light'):
                for suffix in ('','3'):
                    self.assertEqual((dist/f'profile-{theme}{suffix}.svg').read_text(),'unchanged original')
                    svg=ET.fromstring((dist/f'activity-{theme}{suffix}.svg').read_text())
                    self.assertEqual(svg.attrib['height'],'600' if suffix else '640')
            self.assertFalse(list(dist.glob('*.json')))
            embed=(dist/'embed.md').read_text()
            self.assertIn('[![activity-dark.webp](/../images/activity-dark3.webp#gh-dark-mode-only)](/../images/activity-dark.webp#gh-dark-mode-only)',embed)
            self.assertNotIn('Daisuke',embed)
            light=(dist/'activity-light.svg').read_text()
            self.assertIn('PRs created <tspan font-weight="700" font-size="20">6</tspan>',light)
            self.assertIn('stroke="#1a7f37"',light)
            self.assertIn('stroke="#8250df"',light)
            self.assertNotIn('Authored · all time',light)
            self.assertNotIn('Public data',light)
            self.assertNotIn('fill=',light.split('PRs created <tspan',1)[1].split('</tspan>',1)[0])
            self.assertNotIn('Repositories &amp; community',light)


    def test_private_scope_is_optional_and_has_separate_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            calls=[]
            def request(*args, **kwargs):
                calls.append(kwargs['body']['query'])
                return response(), {}
            avatar=lambda _: 'data:image/png;base64,AA=='
            activity.collect('OtherUser','token',tmp,'2031-01-01',request,avatar)
            private=activity.collect('OtherUser','PRIVATE_TOKEN',tmp,'2031-01-01',request,avatar,include_private=True)
            self.assertEqual(len(calls),2)
            self.assertIn('is:public',calls[0])
            self.assertIn('privacy: PUBLIC',calls[0])
            self.assertNotIn('is:public',calls[1])
            self.assertNotIn('privacy: PUBLIC',calls[1])
            self.assertEqual(private['scope'],'accessible')
            self.assertIn('token-accessible',activity.render(private))
            activity.collect('OtherUser','token',tmp,'2031-01-01',request,avatar)
            self.assertEqual(len(calls),2)
            saved=(Path(tmp)/'accessible/otheruser/snapshot.json').read_text()
            self.assertNotIn('PRIVATE_TOKEN',saved)
            self.assertNotIn('nodes',saved)

    def test_zero_data_and_escaping(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw=response();raw['data']['user']['repositories']['nodes']=[]
            model=activity.collect('OtherUser','token',tmp,'2031-01-01',lambda *a,**k:(raw,{}),lambda _:'data:image/png;base64,AA==')
            self.assertIn('No detected languages',activity.render(model))
            model['user']='A<&'
            ET.fromstring(activity.render(model))


if __name__=='__main__':
    unittest.main()
