import cookielib
import hashlib
import json
import os.path
import re
import sys
import time
import urlparse
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


class Mode:
    MAIN_MENU = 0
    SUB_MENU = 1
    SHOW_LIST = 2
    SHOW_INFO = 3
    PLAY = 4


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
        a = common.parseDOM(sc, 'a', attrs={'data-id': category_id})
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

def get_show_list(url):
    # iterate through all the pages
    htmlData = callServiceApi(url)
    show_lists = get_show_data(htmlData)

    pages = common.parseDOM(htmlData, 'ul',
                            attrs={'id': 'pagination'})
    urls = common.parseDOM(pages, 'a', ret='href')
    for url in urls[1:]:
        common.log(url)
        htmlData = callServiceApi(url)
        show_lists.update(get_show_data(htmlData))

    return show_lists

def get_show_data(htmlContents):

    section = common.parseDOM(htmlContents, "div",
                              attrs={'class': 'main'})
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

def show_tv_episode_list(show_id, show_details_page, title, page):

    pages = common.parseDOM(show_details_page, 'ul',
                            attrs={'id': 'pagination'})
    # url = '/modulebuilder/getepisodes/{}/{}'.format(show_id, page)
    urls = common.parseDOM(pages, 'a', ret='href')

    episodes_shown = 0
    exit = False
    for url in urls[page:]:

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

        episode_list = zip(date_list, urls, show_cover_list, desc_list)

        for name, episode_url, image_url, plot in episode_list:

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
            addDir(name, urlparse.urlparse(episode_url).path,
                   Mode.PLAY, image_url, isFolder=False,
                   **kwargs)

            if episodes_shown >= int(this.getSetting('itemsPerPage')):
                addDir('NEXT >>>', show_id, Mode.SHOW_INFO, '', page=page+1)
                exit = True
                break


    xbmcplugin.endOfDirectory(thisPlugin)

def show_show_info(show_id, page):

    show_details = callServiceApi('/show/details/%s' % (show_id))

    # synopsis
    e = common.parseDOM(show_details, 'meta',
                        attrs={'property': 'og:description'},
                        ret='content'
                       )
    plot = common.replaceHTMLCodes(e[0])
    e = common.parseDOM(show_details, 'meta',
                        attrs={'property': 'og:title'},
                        ret='content'
                       )
    title = common.replaceHTMLCodes(e[0])

    # logo
    e = common.parseDOM(show_details, 'meta',
                        attrs={'property': 'og:image'},
                        ret='content'
                       )
    image_url = common.replaceHTMLCodes(e[0])

    episode_list = []

    if 'modulebuilder' in show_details:
        show_tv_episode_list(show_id, show_details, title, page)
    else:
        # no episodes, maybe this is a movie page

        e = common.parseDOM(show_details, 'a',
                            attrs={'class': 'hero-image-orange-btn'},
                            ret='href')
        if len(e) == 0:
            # assume live show
            e = common.parseDOM(show_details, 'meta',
                                attrs={'property': 'og:url'},
                                ret='content'
                               )
            episode_url = e[0]
            name = title
        else:
            # movies section
            episode_url = e[0]
            # title and date
            topic_bg_e = common.parseDOM(show_details, 'div',
                                         attrs={'class': 'topic-section-bg'})[0]
            rating_e = common.parseDOM(topic_bg_e, 'div',
                                       attrs={'class': 'hero-image-rating'})[0]
            episode_date = rating_e.split('|')[0].replace('&nbsp;', '').strip()

            name = '%s - %s' % (title, episode_date)

        episode_list.append((name, episode_url, image_url))

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

        for name, episode_url, image_url in episode_list:
            addDir(name, urlparse.urlparse(episode_url).path,
                   Mode.PLAY, image_url, isFolder=False,
                   **kwargs)

        xbmcplugin.endOfDirectory(thisPlugin)

def play_video(episode_url, thumbnail):

    episodeDetails = {}

    for i in range(int(this.getSetting('loginRetries')) + 1):
        episodeDetails = get_media_info(episode_url)
        if episodeDetails:
            break
        if episodeDetails and episodeDetails.get('StatusCode', 0) != 0 and \
                episodeDetails.get('UserType', 'GUEST') == 'REGISTERED':
            break
        else:
            login()

    if episodeDetails and episodeDetails.get('StatusCode', 0) != 0:
        media_url = episodeDetails['MediaReturnObj']['uri']
        # fix pixelation per @cmik tfc.tv v0.0.58
        media_url = media_url.replace('&b=100-1000', '')

        liz = xbmcgui.ListItem(name, iconImage="DefaultVideo.png",
                               thumbnailImage=thumbnail, path=media_url)
        liz.setInfo(type="Video", infoLabels={"Title": name})
        liz.setProperty('IsPlayable', 'true')

        return xbmcplugin.setResolvedUrl(thisPlugin, True, liz)
    else:
        xbmc.executebuiltin('Notification(%s, %s)' % \
                            ('Media Error', 'Subscription is already expired \
                                             or the item is not part of your \
                                             subscription.'))
    return False

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
    for c in cookieJar:
        cookies.append('%s=%s' % (c.name, c.value))
    cookies.append('cc_fingerprintid=%s' % \
                    (hashlib.md5(
                        this.getSetting('emailAddress')).hexdigest()))

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
                                  params={'id': episode_id, 'pv': False},
                                  headers=headers)
        common.log('MEDIA_INFO')
        common.log(response)
        common.log(match.group(0))
        common.log(match.group(1))
        common.log(match.group(2))
        media_info = json.loads(response)

    return media_info

def callServiceApi(path, params=None, headers=None, base_url=baseUrl,
                   timeout=20):
    if not params:
        params = {}
    if not headers:
        headers = []

    opener = urllib2.build_opener(urllib2.HTTPCookieProcessor(cookieJar))

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
    cookieJar.clear()
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
           data_id=0, **kwargs):
    u = sys.argv[0] + \
            "?url=" + urllib.quote_plus(url) + \
            "&mode=" + str(mode) + \
            "&name=" +urllib.quote_plus(name) + \
            "&page=" + str(page) + \
            "&thumbnail=" + urllib.quote_plus(thumbnail) + \
            "&data_id=" + str(data_id)

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

def showMessage(message, title = xbmcaddon.Addon().getLocalizedString(50107)):
    if not message:
        return
    xbmc.executebuiltin("ActivateWindow(%d)" % (10147, ))
    win = xbmcgui.Window(10147)
    xbmc.sleep(100)
    win.getControl(1).setLabel(title)
    win.getControl(5).setText(message)

thisPlugin = int(sys.argv[1])

cookieJar = cookielib.CookieJar()
cookieFile = ''
cookieJarType = ''
if os.path.exists(
        xbmc.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))):
    cookieFile = os.path.join(xbmc.translatePath(
            xbmcaddon.Addon().getAddonInfo('profile')), 'tfctv.cookie')
    cookieJar = cookielib.LWPCookieJar(cookieFile)
    cookieJarType = 'LWPCookieJar'

if cookieJarType == 'LWPCookieJar':
    try:
        cookieJar.load()
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
data_id = '0'

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
try:
    data_id = params["data_id"]
except:
    pass

if mode == None or url == None or len(url) < 1:
    show_main_menu()
elif mode == Mode.SUB_MENU:
    showSubCategories(url, data_id)
elif mode == Mode.SHOW_LIST:
    showShows(url)
elif mode == Mode.SHOW_INFO:
    show_show_info(url, page)
elif mode == Mode.PLAY:
    play_video(url, thumbnail)

if cookieJarType == 'LWPCookieJar':
    cookieJar.save()

if this.getSetting('announcement') != this.getAddonInfo('version'):
    cookieJar.clear()
    try:
        cookieFile = os.path.join(xbmc.translatePath(
                xbmcaddon.Addon().getAddonInfo('profile')), 'tfctv.cookie')
        os.remove(cookieFile)
    except:
        pass

    messages = {
        '0.1.0': 'Your TFC.tv addon has been updated.',
        '0.1.1': 'Your TFC.tv addon has been updated.',
        '0.1.2': 'Movies should work now.\n\nPress "Back" to continue.',
        '0.1.3': 'Movies should work now.'
                 '\n\nPress "Back" to continue.',
        '0.1.4': 'CHANGES'
                 '\n* Fix version not updated'
                 '\n* Increase request timeout'
                 '\n\nPress "Back" to continue.',
        '0.1.5': 'CHANGES'
                 '\n* Fix compatibility with minor web UI update',
        '0.1.6': 'CHANGES'
                 '\n* Fix pixelation',
        '0.1.7': 'CHANGES'
                 '\n* Fix live TV shows',
        }

    xbmcaddon.Addon().setSetting('announcement',
                                 this.getAddonInfo('version'))

    if this.getAddonInfo('version') in messages:
        showMessage(messages[this.getAddonInfo('version')],
                    xbmcaddon.Addon().getLocalizedString(50106))
