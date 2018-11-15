#!/usr/bin/env python2
import SocketServer
import re
import sys
import threading
import time

from SimpleHTTPServer import SimpleHTTPRequestHandler
import requests
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
ext_key_pat = re.compile("(.*)URI=\"(.*)\"")


def debug(s):
    sys.stdout.write(s)


class ProxyHandler(SimpleHTTPRequestHandler):

    def do_GET(self):

        q = urlparse.parse_qs(urlparse.urlparse(self.path).query)
        url = q["url"][0]
        host = urlparse.urlsplit(url)

        headers = {"user-agent": USER_AGENT, "accept": "*/*", "host": host.netloc}
        for h in self.headers:
            if h in ["icy-metadata", "range"] or h in headers:
                continue
            headers[h] = self.headers[h] 

        debug("HEADERS: %s\n" %  headers)
        debug("%s\n" % url)

        s = requests.Session()
        res = s.get(url, headers=headers)
        
        debug("Response length: %d\n" % len(res.content))
        debug("Content Type: %s\n" % res.headers["Content-Type"])

        body = res.content
        if "application/vnd.apple.mpegurl" in res.headers['Content-Type']:
            # it's a playlist.  Route to our proxy server.
            out = []
            for line in body.splitlines(False):
                if line.startswith("http"):
                    line = "http://localhost:1704/?url=" + urllib2.quote(line)
                elif line.startswith("#EXT-X-KEY"):
                    # reroute the encryption key url
                    m = ext_key_pat.search(line)
                    if m:
                        line = "%sURI=\"http://localhost:1704/?url=%s\"" % (m.group(1),
                                                                            urllib2.quote(m.group(2)))
                    
                out.append(line)
            self.send(res, '\n'.join(out))
        else:
            self.send(res, body)

        debug("EXIT\n")

    def send(self, res, body):

        # headers
        self.send_response(res.status_code, res.reason)
        for h in res.headers:
            if h == "Transfer-Encoding":
                continue

            if h == "Content-Length":
                self.send_header(h, len(body))
            else:
                self.send_header(h, res.headers[h])
        self.end_headers()
        self.wfile.write(body)
        

def start():
    if XBMC:
        livestreamer_port = int(this.getSetting('livestreamer_port'))
    else:
        livestreamer_port = 1704
    SocketServer.TCPServer.allow_reuse_address = True
    server = SocketServer.TCPServer(('', livestreamer_port), ProxyHandler)

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
