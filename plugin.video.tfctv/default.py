import cookielib
import hashlib
import json
import os.path
import random
import re
import sys
import time
import urlparse
# import this before urllib2 to fix urlopen error 0
try:
    import OpenSSL
except:
    # only needed on nix machines?
    pass
import urllib
import urllib2

import xbmc, xbmcgui, xbmcplugin, xbmcaddon
from operator import itemgetter

import CommonFunctions
common = CommonFunctions
this = xbmcaddon.Addon()
common.plugin = this.getAddonInfo('name')
baseUrl = 'http://tfc.tv'

common.dbg = True
common.dbglevel = 3

userAgent = 'Mozilla/5.0 (iPad; CPU OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B143 Safari/601.1'

user_data_dir = xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
COOKIEFILE = os.path.join(user_data_dir, 'tfctv.cookie')
cookie_jar = cookielib.LWPCookieJar(COOKIEFILE)


class Mode:
    MAIN_MENU = 0
    SUB_MENU = 1
    SHOW_LIST = 2
    SHOW_INFO = 3
    PLAY = 4
    CLEAR_COOKIES = 5


def show_main_menu():
    """Show the main categories

    This is typically: Shows, News, Movies, Live
    """

    checkAccountChange()

    html = callServiceApi('/')

    processed = []
    category_ids = common.parseDOM(html, 'a', ret='data-id')
    for id in category_ids:
        name = common.parseDOM(html, 'a', attrs={'data-id': id})[0]
        href = common.parseDOM(html, 'a', attrs={'data-id': id}, ret='href')[0]
        if id not in processed:
            addDir(name, href, Mode.SUB_MENU, 'icon.png', data_id=id)
            processed.append(id)

    addDir('Clear cookies', '/', Mode.CLEAR_COOKIES, 'icon.png', isFolder=False)

    xbmcplugin.endOfDirectory(thisPlugin)

def showSubCategories(url, category_id):
    """Show sub category

    Under Shows category, typically this is a list
    - All Shows
    - Drama
    - Subtitled Show
    - etc
    """

    html = callServiceApi(url)
    main_nav = common.parseDOM(html, "div",
                               attrs={'id': 'main_nav_desk'})[0]
    sub_categories = \
        common.parseDOM(main_nav, 'li', attrs={'class': 'has_children'})

    for sc in sub_categories:
        a = common.parseDOM(sc, 'a', attrs={'data-id': str(category_id)})
        if len(a) > 0:
            ul = common.parseDOM(sc, 'ul', attrs={'class': 'menu_item'})[0]
            for li in common.parseDOM(ul, 'li'):
                url = common.parseDOM(li, 'a', ret='href')[0]
                name = common.parseDOM(li, 'a')[0]
                addDir(common.replaceHTMLCodes(name), url,
                       Mode.SHOW_LIST, 'menu_logo.png')
            break

    xbmcplugin.endOfDirectory(thisPlugin)

def showShows(category_url):
    """Display all shows under a sub category

    params:
        category_url: a sub category is a unique id
    """

    showListData = get_show_list(category_url)
    if showListData is None:
        xbmcplugin.endOfDirectory(thisPlugin)
        return

    for show_id, (title, thumbnail) in showListData.iteritems():
        addDir(title, str(show_id), Mode.SHOW_INFO, thumbnail)

    xbmcplugin.addSortMethod(thisPlugin, xbmcplugin.SORT_METHOD_LABEL_IGNORE_THE)
    xbmcplugin.endOfDirectory(thisPlugin)

def get_show_list(catgory_url):
    # iterate through all the pages
    category_page = callServiceApi(catgory_url)
    show_lists = parse_category_list(category_page)

    e = common.parseDOM(category_page, 'ul',
                        attrs={'id': 'pagination'})
    pages = common.parseDOM(e, 'a', ret='href')
    for page in pages[1:]:
        common.log(page)
        category_page = callServiceApi(page)
        show_lists.update(parse_category_list(category_page))

    return show_lists

def parse_category_list(html):

    section = common.parseDOM(html, "div", attrs={'class': 'main'})
    show_data = {}
    for header in section:
        shows = common.parseDOM(header, 'li')
        for show in shows:
            url = common.parseDOM(show, 'a', ret='href')[0]
            title = common.parseDOM(show, 'h2')[0]
            show_id = url.replace('/show/details/', '').split('/')[0]
            thumbnail = common.parseDOM(show, "img", ret='src')[0]

            show_data[show_id] = \
                (common.replaceHTMLCodes(title.encode('utf8')), thumbnail)

    return show_data

def show_tv_episode_list(show_id, show_details_page, title, page, page_item):
    """Construct a list of episodes

    Args:
        show_id: a unique show identifier
        show_details_page: html source of the show details page
        title: this show's title
        page: start with this page
        page_item: start with this item in the list within this page
    """

    pages = common.parseDOM(show_details_page, 'ul',
                            attrs={'id': 'pagination'})
    urls = common.parseDOM(pages, 'a', ret='href')

    page_offset = page
    episode_offset = page_item
    episodes_shown = 0
    exit = False
    for url in urls[page_offset:]:

        if exit:
            break

        e = callServiceApi(url)
        grid_e = common.parseDOM(e, 'ul', attrs={'id': 'og-grid'})[0]
        desc_list = common.parseDOM(grid_e, 'li',
                                    attrs={'class': 'og-grid-item'},
                                    ret='data-show-description')
        date_list = common.parseDOM(grid_e, 'li',
                                    attrs={'class': 'og-grid-item'},
                                    ret='data-aired')
        show_cover_list = common.parseDOM(grid_e, 'div',
                                          attrs={'class': 'show-cover'},
                                          ret='data-src')
        urls = common.parseDOM(grid_e, 'a', ret='href')

        episodes_in_page = zip(date_list, urls, show_cover_list, desc_list)

        for name, episode_url, image_url, plot in \
                episodes_in_page[episode_offset:]:

            kwargs = {
                'listProperties': {
                    'IsPlayable': 'true'
                },
                'listInfos': {
                    'video': {
                        'plot': plot, 'title': title,
                    }
                }
            }

            episodes_shown += 1
            episode_offset += 1
            addDir(name, urlparse.urlparse(episode_url).path,
                   Mode.PLAY, image_url, isFolder=False,
                   **kwargs)
            if episodes_shown >= int(this.getSetting('itemsPerPage')):
                addDir('NEXT >>>', show_id, Mode.SHOW_INFO, '',
                       page=page_offset,
                       page_item=episode_offset)
                exit = True
                break

        if episode_offset > len(episodes_in_page) - 1:
            # parsed all episodes in this page
            page_offset += 1
            episode_offset = 0

    xbmcplugin.endOfDirectory(thisPlugin)

def show_show_info(show_id, page, page_item):

    show_details = callServiceApi('/show/details/%s' % (show_id))

    e = common.parseDOM(show_details, 'meta',
                        attrs={'property': 'og:title'},
                        ret='content'
                       )
    title = common.replaceHTMLCodes(e[0])
    if 'modulebuilder' in show_details:
        # multiple episodes exist
        show_tv_episode_list(show_id, show_details, title, page, page_item)
    else:
        # single episode.  There should be a direct link to the video

        MOVIE = 0
        SHOW = 1
        LIVE = 2

        category = -1

        # logo
        e = common.parseDOM(show_details, 'meta',
                            attrs={'property': 'og:image'},
                            ret='content'
                           )
        image_url = common.replaceHTMLCodes(e[0])

        # synopsis
        e = common.parseDOM(show_details, 'meta',
                            attrs={'property': 'og:description'},
                            ret='content'
                           )
        plot = common.replaceHTMLCodes(e[0])

        episode_url_dom = [
            # movies
            (MOVIE, 'a',
                {'attrs': {'class': 'hero-image-orange-btn'}, 'ret': 'href'}),
            # shows/specials, shows/sports, episode also has this link
            (SHOW, 'a',
                {'attrs': {'class': 'link-to-episode'}, 'ret': 'href'}),
            # live show
            (LIVE, 'meta',
                {'attrs': {'property': 'og:url'}, 'ret': 'content'})
        ]
        for id, element, kwargs in episode_url_dom:
            e = common.parseDOM(show_details, element, **kwargs)
            if len(e) > 0:
                episode_url = urlparse.urlparse(e[0]).path
                name = title
                category = id
                break

        if id == MOVIE:
            # movies section
            # title and date
            topic_bg_e = common.parseDOM(show_details, 'div',
                                         attrs={'class': 'topic-section-bg'})[0]
            rating_e = common.parseDOM(topic_bg_e, 'div',
                                       attrs={'class': 'hero-image-rating'})[0]
            episode_date = rating_e.split('|')[0].replace('&nbsp;', '').strip()

            name = '%s - %s' % (title, episode_date)

        kwargs = {
            'listProperties': {
                'IsPlayable': 'true'
            },
            'listInfos': {
                'video': {
                    'plot': plot, 'title': title,
                }
            }
        }

        addDir(name, episode_url,
               Mode.PLAY, image_url, isFolder=False,
               **kwargs)

        xbmcplugin.endOfDirectory(thisPlugin)

def play_video(episode_url, thumbnail):

    episodeDetails = {}

    for i in range(int(this.getSetting('loginRetries')) + 1):
        episodeDetails = get_media_info(episode_url)
        if episodeDetails and episodeDetails.get('StatusCode', 0) == 1:
            break
        else:
            login()

    if episodeDetails and episodeDetails.get('StatusCode', 0) == 1:
        media_url = episodeDetails['MediaReturnObj']['uri']
        # fix pixelation per @cmik tfc.tv v0.0.58
        #media_url = media_url.replace('&b=100-1000', '')
        # fix issue #5 per @gwapoman
        #media_url = media_url.replace('&b=100-1000', '&b=2000-4000')
        #media_url = media_url.replace('http://o2-i.', 'https://life-vh.')

        # re-enable bw limiting in v0.1.12. Streams has very variable rate and
        # without this limits, the stream will drop.
        media_url = media_url.replace('&b=100-1000', '&b=100-6000')

        # fix #9 per cmik.  Only apply if it's non live show
        common.log(episodeDetails['MediaReturnObj']['live'] == False)
        if not episodeDetails['MediaReturnObj']['live']:
            media_url = media_url.replace('http://o2-i.', 'https://o4-vh.')

        liz = xbmcgui.ListItem(name, iconImage="DefaultVideo.png",
                               thumbnailImage=thumbnail, path=media_url)
        liz.setInfo(type="Video", infoLabels={"Title": name})
        liz.setProperty('IsPlayable', 'true')

        return xbmcplugin.setResolvedUrl(thisPlugin, True, liz)
    else:
        default_msg = 'Subscription is already expired \
                       or the item is not part of your \
                       subscription.'
        status_msg = episodeDetails.get('StatusMessage', default_msg)
        xbmc.executebuiltin('Notification(%s, %s)' % \
                            ('Media Error', status_msg))

def get_media_info(episode_url):

    media_info = None

    common.log(episode_url)
    pat = re.compile('details/([\d]+)')

    m = pat.search(episode_url)
    if m:
        episode_id = m.group(1)
    else:
        episode_id = 0
        common.log('episode_id missing')
        common.log(episode_url)

    html = callServiceApi(episode_url)
    pattern = re.compile('([^/]+)\?token=([^\s]+)"', re.IGNORECASE)

    cookies = []
    for c in cookie_jar:
        cookies.append('%s=%s' % (c.name, c.value))
    # I understand now the purpose of cc_fingerprintid better based on
    # cmik v0.0.69 fix.
    fid = hashlib.md5(
        this.getSetting('emailAddress') + str(random.randint(0,1e6))).hexdigest()
    cookies.append('cc_fingerprintid=%s' % fid)

    match = pattern.search(html)
    if match:
        media_token = match.group(2)
        headers = [
            ('Host', 'tfc.tv'),
            ('Accept', 'application/json, text/javascript, */*; q=0.01'),
            ('X-Requested-With', 'XMLHttpRequest'),
            ('mediaToken', media_token),
            ('Content-Type', "application/x-www-form-urlencoded; charset=UTF-8"),
            ('Cookie', '; '.join(cookies)),
        ]
        response = callServiceApi('/media/get',
                                  params={'id': episode_id, 'pv': False,
                                          'sk': fid},
                                  headers=headers)
        common.log('MEDIA_INFO')
        common.log(response)
        common.log(match.group(0))
        common.log(match.group(1))
        common.log(match.group(2))
        media_info = json.loads(response)

    return media_info

def callServiceApi(path, params=None, headers=None, base_url=baseUrl,
                   timeout=60):
    if not params:
        params = {}
    if not headers:
        headers = []

    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookie_jar))

    headers.append(('User-Agent', userAgent))
    opener.addheaders = headers
    common.log('HEADERS')
    common.log(path)
    common.log(headers)
    if params:
        data_encoded = urllib.urlencode(params)
        response = opener.open(base_url + path, data_encoded, timeout=timeout)
    else:
        response = opener.open(base_url + path, timeout=timeout)
    return response.read()

def login():
    cookie_jar.clear()
    login_page = callServiceApi("/user/login")
    form_login = common.parseDOM(login_page, "form", attrs = {'id' : 'form1'})
    request_verification_token = common.parseDOM(
        form_login[0], "input",
        attrs = {'name': '__RequestVerificationToken'}, ret='value'
    )
    emailAddress = this.getSetting('emailAddress')
    password = this.getSetting('password')
    formdata = {"EMail": emailAddress,
                "Password": password,
                '__RequestVerificationToken': request_verification_token[0]
               }
    headers = [('Referer', 'http://tfc.tv/User/Login')]
    response = callServiceApi("/user/login", formdata, headers=headers,
                              base_url='https://tfc.tv', timeout=120)
    common.log('LOGIN_STATUS')
    if 'logout' in response:
        common.log('LOGGED IN')
    else:
        xbmc.executebuiltin('Sign In Error')

def checkAccountChange():
    emailAddress = this.getSetting('emailAddress')
    password = this.getSetting('password')
    hash = hashlib.sha1(emailAddress + password).hexdigest()
    hashFile = os.path.join(
                    xbmc.translatePath(
                            xbmcaddon.Addon().getAddonInfo('profile')),
                    'a.tmp')
    savedHash = ''
    accountChanged = False
    if os.path.exists(hashFile):
        with open(hashFile) as f:
            savedHash = f.read()
    if savedHash != hash:
        login()
        accountChanged = True
    if os.path.exists(
            xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))):
        with open(hashFile, 'w') as f:
            f.write(hash)
    return accountChanged

def getParams():
    param = {}
    paramstring = sys.argv[2]
    if len(paramstring) >= 2:
        params = sys.argv[2]
        cleanedparams = params.replace('?','')
        if (params[len(params)-1] == '/'):
            params = params[0:len(params)-2]
        pairsofparams = cleanedparams.split('&')
        param = {}
        for i in range(len(pairsofparams)):
            splitparams = {}
            splitparams = pairsofparams[i].split('=')
            if (len(splitparams)) == 2:
                param[splitparams[0]] = splitparams[1]

    return param

def addDir(name, url, mode, thumbnail, page=0, isFolder=True,
           data_id=0, page_item=0, **kwargs):
    u = ('%s?url=%s&mode=%s&name=%s&page=%s' \
         '&thumbnail=%s&data_id=%s&page_item=%s' % (
            sys.argv[0],
            urllib.quote_plus(url),
            str(mode),
            urllib.quote_plus(name),
            str(page),
            urllib.quote_plus(thumbnail),
            str(data_id),
            str(page_item)
        ))
    liz = xbmcgui.ListItem(name, iconImage="DefaultFolder.png",
                           thumbnailImage=thumbnail)
    liz.setInfo( type="Video", infoLabels={ "Title": name } )
    for k, v in kwargs.iteritems():
        if k == 'listProperties':
            for listPropertyKey, listPropertyValue in v.iteritems():
                liz.setProperty(listPropertyKey, listPropertyValue)
        if k == 'listInfos':
            for listInfoKey, listInfoValue in v.iteritems():
                liz.setInfo(listInfoKey, listInfoValue)

    return xbmcplugin.addDirectoryItem(handle=thisPlugin,
                                       url=u,
                                       listitem=liz,
                                       isFolder=isFolder)

def show_message(message, title=xbmcaddon.Addon().getLocalizedString(50107)):
    if not message:
        return
    xbmc.executebuiltin("ActivateWindow(%d)" % (10147, ))
    win = xbmcgui.Window(10147)
    xbmc.sleep(100)
    win.getControl(1).setLabel(title)
    win.getControl(5).setText(message)

def clear_cookies():
    try:
        os.remove(COOKIEFILE)
    except:
        pass

thisPlugin = int(sys.argv[1])

try:
    cookie_jar.load()
except Exception as e:
    common.log(e)
    login()

common.log(sys.argv)
params = getParams()
url = None
name = None
mode = None
page = 0
thumbnail = ''

try:
    url = urllib.unquote_plus(params["url"])
except:
    pass
try:
    name = urllib.unquote_plus(params["name"])
except:
    pass
try:
    mode = int(params["mode"])
except:
    pass
try:
    page = int(params["page"])
except:
    pass
try:
    thumbnail = urllib.unquote_plus(params["thumbnail"])
except:
    pass

data_id = int(params.get('data_id', 0))
page_item = int(params.get('page_item', 0))

if mode == None or url == None or len(url) < 1:
    show_main_menu()
elif mode == Mode.SUB_MENU:
    showSubCategories(url, data_id)
elif mode == Mode.SHOW_LIST:
    showShows(url)
elif mode == Mode.SHOW_INFO:
    show_show_info(url, page, page_item)
elif mode == Mode.PLAY:
    play_video(url, thumbnail)
elif mode == Mode.CLEAR_COOKIES:
    clear_cookies()
    common.log(this)
    xbmc.executebuiltin('Notification(%s, %s)' % \
                        ('Cookies Removed', ''))
    

# before we leave, save the current cookies
cookie_jar.save()

if this.getSetting('announcement') != this.getAddonInfo('version'):
    clear_cookies()
