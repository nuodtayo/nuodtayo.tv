#!/usr/bin/env python2
import SocketServer
import re
import sys
import threading
import time

from SimpleHTTPServer import SimpleHTTPRequestHandler
import requests
import urllib
import urllib2
from urllib2 import urlparse

try:
    import xbmc
    import xbmcaddom
    XBMC = True
    this = xbmcaddon.Addon()
except ImportError:
    XBMC = False


USER_AGENT = 'Mozilla/5.0 (X11; CrOS x86_64 11021.56.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.76 Safari/537.36'

cache = {}
uri_pat = re.compile("(.*)URI=\"(.*)\"")


def debug(s):
    sys.stdout.write(s)

active = 0


class ProxyHandler(SimpleHTTPRequestHandler):

    def do_HEAD(self):
        self._handle(is_get=False)

    def do_GET(self):
        self._handle(is_get=True)

    def handle(self):
        global active
        debug("$$$$$$$$$$$$$$$$$$$$$$$$$\n")
        active += 1
        SimpleHTTPRequestHandler.handle(self)
        active -= 1
        debug("$$$$$$$$$$$$$$$$$$$$$$$$$ ACTIVE: %0d\n" % active)

    def _handle(self, is_get):

        debug('#\n'*30)
        debug(self.path + "\n")
        q = urlparse.parse_qs(urlparse.urlparse(self.path).query)
        url = q["url"][0]
        host = urlparse.urlsplit(url)

        headers = {"user-agent": USER_AGENT,
                   "accept": "*/*",
                   "host": host.netloc,
                   "connection": "keep-alive",
                   "keep-alive": "timeout=5, max=1000",
                  }
        for h in self.headers:
            if h.lower() in ["icy-metadata", "range"] or h in headers:
                continue
            headers[h] = self.headers[h]

        debug("HEADERS: %s\n" %  headers)
        debug("%s\n" % url)

        s = cache[url] if url in cache else requests.Session()
        res = s.get(url, headers=headers)

        debug("Response length: %d\n" % len(res.content))
        debug("Content Type: %s\n" % res.headers["Content-Type"])
        debug("Reponse Code: %s\n" % res.status_code)

        body = res.content
        url = "%s://%s/" % (host.scheme, host.netloc)
        if "application/vnd.apple.mpegurl" in res.headers['Content-Type'] or \
                "audio/x-mpegurl" in res.headers["Content-Type"]:
            # it's a playlist.  Route to our proxy server.
            out = []
            for line in body.splitlines(False):
                if line.startswith("http"):
                    line = "http://localhost:1704/?url=" + urllib.quote_plus(line)
                elif line and not line.startswith("#EXT"):
                    line = "http://localhost:1704/?url=" + urllib.quote_plus(url + "/" + line)
                elif line.startswith("#EXT-X-KEY"):
                    # reroute the encryption key url
                    m = uri_pat.search(line)
                    if m:
                        line = "%sURI=\"http://localhost:1704/?url=%s\"" % (m.group(1),
                                                                            urllib.quote_plus(m.group(2)))

                elif line.startswith("#EXT-X-MEDIA"):
                    m = uri_pat.search(line)
                    if m:
                        uri = urllib.quote_plus(url + "/" + m.group(2))
                        line = "%sURI=\"http://localhost:1704/?url=%s\"" % (m.group(1), uri)
                out.append(line)
            self.send(res, '\n'.join(out), is_get)
        else:
            self.send(res, body, is_get)

        debug("EXIT\n")

    def send(self, res, body, is_get):

        # headers
        self.send_response(res.status_code, res.reason)
        for h in res.headers:
            h = h.lower()
            if h == "transfer-encoding":
                continue

            if h == "content-length":
                self.send_header(h, len(body))
            else:
                if h == "set-cookie":
                    print(h)
                    print(res.headers[h])
                self.send_header(h, res.headers[h])
        self.end_headers()

        if is_get:
            self.wfile.write(body)

def start():
    if XBMC:
        proxy_port = int(this.getSetting('livestreamer_port'))
    else:
        proxy_port = 1704
    SocketServer.ThreadingTCPServer.allow_reuse_address = True
    server = SocketServer.ThreadingTCPServer(('', proxy_port), ProxyHandler)

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.start()

    # XBMC loop
    if XBMC:
        monitor = xbmc.Monitor()
        while not monitor.waitForAbort(10):
            try:
                time.sleep(100)
            except:
                break
    else:
        while True:
            try:
                time.sleep(100)
            except:
                break


    server.shutdown()
    server_thread.join()

if __name__ == "__main__":
    start()
