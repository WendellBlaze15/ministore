import urllib.request
html = urllib.request.urlopen('http://127.0.0.1:5000/').read().decode('utf-8')
need = [
    ('html.js class is injected in <head>', "classList.add('js')"),
    ('reveal CSS scoped to html.js',        'html.js [data-reveal]'),
    ('hero CTA "Shop the collection"',      'Shop the collection'),
    ('category tiles present',              'cat-tile'),
    ('hero gallery images present',         'hero-card'),
    ('featured/empty section rendered',     'Fresh from the studio'),
    ('newsletter CTA',                       'Get 10% off your first order'),
]
all_ok = True
for label, needle in need:
    ok = needle in html
    all_ok = all_ok and ok
    print(('[ok]' if ok else '[!!]'), label)
print('\nTOTAL: ', 'all sections rendered & reveal is JS-gated' if all_ok else 'something missing')
