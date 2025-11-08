#
# Copyright (C) 2025 pdnguyen of HCMC University of Technology VNU-HCM.
# All rights reserved.
# This file is part of the CO3093/CO3094 course.
#
# WeApRous release
#
# The authors hereby grant to Licensee personal permission to use
# and modify the Licensed Source Code for the sole purpose of studying
# while attending the course
#

"""
daemon.request
~~~~~~~~~~~~~~~~~

This module provides a Request object to manage and persist 
request settings (cookies, auth, proxies).
"""
from .dictionary import CaseInsensitiveDict
from urllib.parse import urlencode, parse_qs
import json 


class Request():
    """The fully mutable "class" `Request <Request>` object,
    containing the exact bytes that will be sent to the server.

    Instances are generated from a "class" `Request <Request>` object, and
    should not be instantiated manually; doing so may produce undesirable
    effects.

    Usage::

      >>> import deamon.request
      >>> req = request.Request()
      ## Incoming message obtain aka. incoming_msg
      >>> r = req.prepare(incoming_msg)
      >>> r
      <Request>
    """
    __attrs__ = [
        "method",
        "url",
        "headers",
        "body",
        "reason",
        "cookies",
        "routes",
        "hook",
        "path",
        "version",
    ]


    def __init__(self):
        #: HTTP verb (GET/POST/...)
        self.method = None
        #: Original URL if any (not required for inbound)
        self.url = None
        #: Headers dictionary (lowercased keys)
        self.headers = {}
        #: Request path
        self.path = None
        #: HTTP version
        self.version = "HTTP/1.1"
        #: Cookies parsed from Cookie header
        self.cookies = {}
        #: Raw body string
        self.body = ""
        #: Routes mapping (WeApRous)
        self.routes = {}
        #: Matched route handler (callable) or None
        self.hook = None

    def extract_request_line(self, request):
        try:
            lines = request.splitlines()
            if not lines:
                return None, None, None

            first_line = lines[0]
            parts = first_line.split()

            if len(parts) != 3:
                return None, None, None

            method, path, version = parts
            return method.upper(), path, version
        
        except Exception as e:
            print(f"[Request] Error parsing request line: {e}")
            return None, None, None
             
    def prepare_headers(self, request):
        """
        Prepares the given HTTP headers.
        """
        lines = request.split('\r\n')
        headers = {}
        for line in lines[1:]:
            if ': ' in line:
                key, val = line.split(': ', 1)
                headers[key.lower()] = val
        return headers
    
    
    def prepare_body(self, request):
        try:
            parts = request.split('\r\n\r\n', 1)
            if len(parts) == 2:
                return parts[1]
            return ""
        except Exception as e:
            print(f"[Request] Error extracting body: {e}")
            return ""

    def parse_cookies(self, cookie_string: str):
        """Parse Cookie header into dict."""
        cookies = {}
        if not cookie_string:
            return cookies
        for pair in cookie_string.split(";"):
            pair = pair.strip()
            if "=" in pair:
                k, v = pair.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies
    
    
    def prepare(self, request, routes=None):
        """Prepares the entire request with the given parameters."""

        # Prepare the request line from the request header
        self.method, self.path, self.version = self.extract_request_line(request)
        if not self.method or not self.path:
            print("[Request] Failed to parse request line")
            return
        
        print(f"[Request] {self.method} path {self.path} version {self.version}")

        #
        # @bksysnet Preapring the webapp hook with WeApRous instance
        # The default behaviour with HTTP server is empty routed
        #
        # TODO manage the webapp hook in this mounting point
        #
        
        # Headers
        self.headers = self.prepare_headers(request)

        # Body + form
        if self.method in ("POST", "PUT", "PATCH"):
            self.body = self.prepare_body(request)
            print(f"[Request] Body extracted ({len(self.body)} bytes): {self.body[:100]}")
        else:
            self.body = ""
    
        # Cookies
        cookie_header = self.headers.get("cookie", "")
        if cookie_header:
            print(f"[Request] Cookies found: {cookie_header}")
            self.cookies = self.parse_cookies(cookie_header)
        else:
            self.cookies = {}

        # Routes / hook
        if routes:
            self.routes = routes
            self.hook = routes.get((self.method, self.path))
            if self.hook:
                print(f"[Request] Route matched: {(self.method, self.path)} -> {self.hook.__name__}")
            else:
                print(f"[Request] No route found for: {(self.method, self.path)}")
                print(f"[Request] Available routes: {list(routes.keys())}")


    def prepare_content_length(self, body):
        if body is not None:
            length = len(body.encode("utf-8")) if isinstance(body, str) else len(body)
            if length:
                self.headers["content-length"] = str(length)
        elif (self.method not in ["GET", "HEAD"]) and ("content-length" not in self.headers):
            self.headers["content-length"] = "0"


    def prepare_auth(self, auth, url=""):
        #
        # TODO prepare the request authentication
        #
	# self.auth = ...
        #  Nếu không truyền auth vào thì thử lấy từ URL (vd: http://user:pass@host) (Nhien)
        if auth is None and url:
            from .utils import get_auth_from_url
            url_auth = get_auth_from_url(url)
            print(f"[Request] URL auth extracted: {url_auth}")
            auth = url_auth if url_auth != ("", "") else None

        try:
            if callable(auth):
                r = auth(self)
                if r is not None and hasattr(r, "__dict__"):
                    self.__dict__.update(r.__dict__)

            #  Dù có auth hay không, vẫn đảm bảo Content-Length hợp lệ
            self.prepare_content_length(self.body)

        except Exception as e:
            print(f"[Request] prepare_auth error: {e}")

    def prepare_cookies(self, cookies):
            self.headers["cookie"] = cookies
