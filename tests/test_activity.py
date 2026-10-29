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
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity, 'MAX_REQUESTS', 2):
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
            self.assertIn('ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]',calls[1])
            for field in ('object(', 'text', 'blob', 'tree', 'contents', 'nameWithOwner'):
                self.assertNotIn(field,calls[1])
            self.assertEqual(private['scope'],'accessible')
            self.assertNotIn('Language bytes across',activity.render(private))
            self.assertNotIn('PRs / issues:',activity.render(private))
            activity.collect('OtherUser','token',tmp,'2031-01-01',request,avatar)
            self.assertEqual(len(calls),2)
            saved=(Path(tmp)/'accessible/otheruser/snapshot.json').read_text()
            self.assertNotIn('PRIVATE_TOKEN',saved)
            self.assertNotIn('nodes',saved)

    def test_organization_pages_aggregate_without_persisting_repository_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            first=response(True, 'personal-id')
            second=response(False, 'organization-private-id')
            second['data']['user']['repositories']['totalCount']=2
            second['data']['user']['repositories']['nodes'].append(
                copy.deepcopy(first['data']['user']['repositories']['nodes'][0]))
            # Duplicate during pagination must not inflate aggregates.
            pages=iter([first,second])
            model=activity.collect('OtherUser','token',tmp,'2031-01-01',
                lambda *a,**k:(next(pages),{}),lambda _:'data:image/png;base64,AA==',include_private=True)
            self.assertEqual(model['sampled'],2)
            self.assertEqual(model['stars'],6)
            self.assertEqual(model['releases'],8)
            self.assertEqual(model['languages'][0]['size'],160)
            saved=(Path(tmp)/'accessible/otheruser/snapshot.json').read_text()
            self.assertNotIn('personal-id',saved)
            self.assertNotIn('organization-private-id',saved)
            self.assertNotIn('nodes',saved)

    def test_transient_errors_reduce_page_size_and_preserve_cursor(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity.time, 'sleep') as sleep:
            calls=[]
            def request(*args, **kwargs):
                calls.append(kwargs['body'])
                if len(calls) == 1:
                    return response(True,'first-page'), {}
                if len(calls) in (2,3):
                    raise activity.APIHTTPError(502)
                return response(False,'second-page'), {}
            model=activity.collect('OtherUser','secret',tmp,'2031-01-01',request,
                                   lambda _:'data:image/png;base64,AA==')
            self.assertEqual(len(calls),4)
            self.assertEqual([c['variables']['cursor'] for c in calls],[None,'first-page','first-page','first-page'])
            for call,size in zip(calls,[25,25,12,6]):
                self.assertIn(f'repositories(first: {size},',call['query'])
            self.assertEqual([c.args[0] for c in sleep.call_args_list],[3,6])
            self.assertEqual(model['sampled'],2)

    def test_retry_limits_and_non_retryable_statuses_do_not_cache_errors(self):
        cases=[(502,None,None,49,3),(503,'12',None,49,3),(504,None,None,2,2),
               (403,None,None,49,1),(429,'60',None,49,1),(401,None,None,49,1),
               (502,None,'0',49,1),(503,'120',None,49,1)]
        for status,after,remaining,budget,expected in cases:
            with self.subTest(status=status,budget=budget,after=after,remaining=remaining):
                with tempfile.TemporaryDirectory() as tmp, patch.object(activity.time,'sleep') as sleep, patch.object(activity,'MAX_REQUESTS',budget):
                    calls=[]
                    def request(*args,**kwargs):
                        calls.append(1)
                        raise activity.APIHTTPError(status,after,remaining)
                    with self.assertRaises(RuntimeError):
                        activity.collect('OtherUser','secret',tmp,'2031-01-01',request)
                    self.assertEqual(len(calls),expected)
                    self.assertFalse(list(Path(tmp).rglob('snapshot.json')))
                    if status==503 and after=='12':
                        self.assertEqual([c.args[0] for c in sleep.call_args_list],[12,12])

    def test_retry_attempts_count_toward_successful_partial_budget(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity.time,'sleep'), patch.object(activity,'MAX_REQUESTS',2):
            calls=[]
            def request(*args,**kwargs):
                calls.append(1)
                if len(calls)==1:
                    raise activity.APIHTTPError(504)
                return response(True), {}
            model=activity.collect('OtherUser','token',tmp,'2031-01-01',request,lambda _:'data:image/png;base64,AA==')
            self.assertEqual(len(calls),2)
            self.assertTrue(model['partial'])

    def test_http_body_is_preserved_and_logged_with_credentials_redacted(self):
        import io
        import urllib.error
        import generate
        body='{"message":"upstream timed out", "detail":"not summarized", "echo":"test-secret"}'
        error=urllib.error.HTTPError('https://api.github.com/graphql',502,'Bad Gateway',
            {'X-GitHub-Request-Id':'request-123'},io.BytesIO(body.encode()))
        with patch.object(generate.urllib.request,'urlopen',side_effect=error), patch.object(generate,'_last_request_finished',None):
            with self.assertRaises(generate.APIHTTPError) as raised:
                generate.request_json('https://api.github.com/graphql',token='test-secret',body={})
        self.assertEqual(raised.exception.response_body,body)
        self.assertEqual(raised.exception.request_id,'request-123')
        with tempfile.TemporaryDirectory() as tmp, patch.object(activity,'MAX_REQUESTS',1), patch('sys.stderr',new_callable=io.StringIO) as stderr:
            def request(*args,**kwargs):
                raise raised.exception
            with self.assertRaises(RuntimeError):
                activity.collect('OtherUser','test-secret',tmp,'2031-01-01',request)
            log=stderr.getvalue()
            self.assertIn('request-123',log)
            self.assertIn('"detail":"not summarized"',log)
            self.assertIn('[REDACTED]',log)
            self.assertNotIn('test-secret',log)

    def test_zero_data_and_escaping(self):
        with tempfile.TemporaryDirectory() as tmp:
            raw=response();raw['data']['user']['repositories']['nodes']=[]
            model=activity.collect('OtherUser','token',tmp,'2031-01-01',lambda *a,**k:(raw,{}),lambda _:'data:image/png;base64,AA==')
            self.assertIn('No detected languages',activity.render(model))
            model['user']='A<&'
            ET.fromstring(activity.render(model))


if __name__=='__main__':
    unittest.main()
