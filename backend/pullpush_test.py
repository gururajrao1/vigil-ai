import httpx
ua = 'VigilAI/1.0'
subs = ['AskDocs', 'pharmacy', 'diabetes', 'cancer', 'AdverseEffects']
total = 0
for sub in subs:
    url = 'https://api.pullpush.io/reddit/search/submission/?subreddit={}&q=side+effect+adverse&size=3'.format(sub)
    try:
        r = httpx.get(url, headers={'User-Agent': ua}, timeout=8)
        if r.status_code == 200:
            items = r.json().get('data', [])
            total += len(items)
            t = items[0].get('title','')[:55] if items else ''
            print('r/{}: {} posts - {}'.format(sub, len(items), t))
        else:
            print('r/{}: {}'.format(sub, r.status_code))
    except Exception as e:
        print('r/{}: err {}'.format(sub, str(e)[:40]))
print('total:', total)
