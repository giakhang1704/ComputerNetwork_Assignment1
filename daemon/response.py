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
daemon.response
~~~~~~~~~~~~~~~~~

This module provides a :class: `Response <Response>` object to manage and persist 
response settings (cookies, auth, proxies), and to construct HTTP responses
based on incoming requests. 

The current version supports MIME type detection, content loading and header formatting
"""
import datetime
import os
import mimetypes
from .dictionary import CaseInsensitiveDict
import json

BASE_DIR = ""

class Response():   
    """The :class:`Response <Response>` object, which contains a
    server's response to an HTTP request.

    Instances are generated from a :class:`Request <Request>` object, and
    should not be instantiated manually; doing so may produce undesirable
    effects.

    :class:`Response <Response>` object encapsulates headers, content, 
    status code, cookies, and metadata related to the request-response cycle.
    It is used to construct and serve HTTP responses in a custom web server.

    :attrs status_code (int): HTTP status code (e.g., 200, 404).
    :attrs headers (dict): dictionary of response headers.
    :attrs url (str): url of the response.
    :attrsencoding (str): encoding used for decoding response content.
    :attrs history (list): list of previous Response objects (for redirects).
    :attrs reason (str): textual reason for the status code (e.g., "OK", "Not Found").
    :attrs cookies (CaseInsensitiveDict): response cookies.
    :attrs elapsed (datetime.timedelta): time taken to complete the request.
    :attrs request (PreparedRequest): the original request object.

    Usage::

      >>> import Response
      >>> resp = Response()
      >>> resp.build_response(req)
      >>> resp
      <Response>
    """

    __attrs__ = [
        "_content",
        "_header",
        "status_code",
        "method",
        "headers",
        "url",
        "history",
        "encoding",
        "reason",
        "cookies",
        "elapsed",
        "request",
        "body",
    ]


    def __init__(self, request=None):
        self._content = b""
        self._content_consumed = False
        self._next = None
        self.status_code = None
        self.headers = {}
        self.url = None
        self.encoding = None
        self.history = []
        self.reason = None
        self.cookies = {}
        self.elapsed = datetime.timedelta(0)
        self.request = None
        self.body = None  


    def get_mime_type(self, path):
        """
        Determines the MIME type of a file based on its path.

        "params path (str): Path to the file.

        :rtype str: MIME type string (e.g., 'text/html', 'image/png').
        """

        try:
            mime_type, _ = mimetypes.guess_type(path)
        except Exception:
            return 'application/octet-stream'
        return mime_type or 'application/octet-stream'


    def prepare_content_type(self, mime_type='text/html'):
        """
        Prepares the Content-Type header and determines the base directory
        for serving the file based on its MIME type.

        :params mime_type (str): MIME type of the requested resource.

        :rtype str: Base directory path for locating the resource.

        :raises ValueError: If the MIME type is unsupported.
        """
        
        base_dir = ""

        # Processing mime_type based on main_type and sub_type
        main_type, sub_type = mime_type.split('/', 1)
        print("[Response] processing MIME main_type={} sub_type={}".format(main_type,sub_type))
        
        if main_type == "text":
            self.headers["Content-Type"] = f"text/{sub_type}"
            if sub_type in ("plain", "css"):
                base_dir = os.path.join(BASE_DIR, "static")
            elif sub_type == "html":
                base_dir = os.path.join(BASE_DIR, "www")
            else:
                raise ValueError(f"Invalid text MIME sub_type: {sub_type}")
            
        elif main_type == "image":
            self.headers["Content-Type"] = f"image/{sub_type}"
            base_dir = os.path.join(BASE_DIR, "static")
            
        elif main_type == "application":
            self.headers["Content-Type"] = f"application/{sub_type}"
            base_dir = os.path.join(BASE_DIR, "apps")
            
        else:
            raise ValueError(f"Invalid MIME type: main_type={main_type} sub_type={sub_type}")

        return base_dir


    def build_content(self, path, base_dir):
        """
        Loads the objects file from storage space.

        :params path (str): relative path to the file.
        :params base_dir (str): base directory where the file is located.

        :rtype tuple: (int, bytes) representing content length and content data.
        """

        filepath = os.path.join(base_dir, path.lstrip('/'))
        print("[Response] serving the object at location {}".format(filepath))
            #
            #  TODO: implement the step of fetch the object file
            #        store in the return value of content
            #
        try:
            with open(filepath, "rb") as f:
                content = f.read()
        except FileNotFoundError:
            return 404, b"404 Not Found"
        except PermissionError:
            print(f"[Response] Permission denied accessing {filepath}")
            return 403, b"403 Forbidden"
        
        return len(content), content
    

    def build_response_header(self, request):
        """
        Constructs the HTTP response headers based on the class:`Request <Request>
        and internal attributes.

        :params request (class:`Request <Request>`): incoming request object.

        :rtypes bytes: encoded HTTP response header.
        """
        status_code = self.status_code or 200
        reasons = {
            200: "OK", 201: "Created", 204: "No Content",
            301: "Moved Permanently", 302: "Found", 304: "Not Modified",
            400: "Bad Request", 401: "Unauthorized", 403: "Forbidden",
            404: "Not Found", 500: "Internal Server Error",
            502: "Bad Gateway", 503: "Service Unavailable",
        }
        reason = reasons.get(status_code, "OK")

        if isinstance(self._content, str):
            self._content = self._content.encode("utf-8")

        headers = {
            "Date": datetime.datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT"),
            "Server": "WeApRous/1.0",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Content-Type": self.headers.get("Content-Type", "text/html; charset=utf-8"),
            "Content-Length": str(len(self._content)),
            "Connection": "close",
        }

        for k, v in self.headers.items():
            headers.setdefault(k, v)

        lines = [f"HTTP/1.1 {status_code} {reason}"]
        
        for k, v in headers.items():
            lines.append(f"{k}: {v}")
            
        header_text = "\r\n".join(lines) + "\r\n\r\n"
        
        return header_text.encode("utf-8")


    def build_notfound(self):
        """
        Constructs a standard 404 Not Found HTTP response.

        :rtype bytes: Encoded 404 response.
        """
        body = b"404 Not Found"
        hdr = (
            "HTTP/1.1 404 Not Found\r\n"
            "Accept-Ranges: bytes\r\n"
            "Content-Type: text/html\r\n"
            f"Content-Length: {len(body)}\r\n"
            "Cache-Control: max-age=86000\r\n"
            "Connection: close\r\n\r\n"
        ).encode("utf-8")
        return hdr + body


    def build_response(self, request):
        """
        Builds a full HTTP response including headers and content based on the request.

        :params request (class:`Request <Request>`): incoming request object.

        :rtype bytes: complete HTTP response using prepared headers and content.
        """
        # 1) Dynamic body from route handler
        if self.body is not None:
            print("[Response] Building dynamic response (from route handler)")
            self._content = self.body if isinstance(self.body, (bytes, bytearray)) else str(self.body).encode("utf-8")
            if self.status_code is None:
                self.status_code = 200
            self._header = self.build_response_header(request)
            return self._header + self._content

        # 2) JSON response from hook_response
        if getattr(request, "hook_response", None) is not None:
            print("[Response] Building JSON response from hook_response")
            data = json.dumps(request.hook_response).encode("utf-8")
            self.headers["Content-Type"] = "application/json"
            self._content = data
            if self.status_code is None:
                self.status_code = 200
            self._header = self.build_response_header(request)
            return self._header + self._content

        # 3) File-based
        path = request.path or "/"
        if path == "/":
            path = "/index.html"  

        print(f"[Response] Building file-based response for path: {path}")
        mime_type = self.get_mime_type(path)
        print(f"[Response] {request.method} path {path} mime_type {mime_type}")

        try:
            if path.endswith(".html") or mime_type == "text/html":
                base_dir = self.prepare_content_type("text/html")
            elif mime_type == "text/css":
                base_dir = self.prepare_content_type("text/css")
            elif mime_type.startswith("image/") or mime_type.startswith("application/"):
                base_dir = self.prepare_content_type(mime_type)
            else:
                return self.build_notfound()
            
        except (ValueError, PermissionError) as e:
            print(f"[Response] Error preparing content type: {e}")
            return self.build_notfound()

        c_len, self._content = self.build_content(path, base_dir)
        
        if c_len == 404:
            return self.build_notfound()
        
        if c_len == 403:
            body = b"403 Forbidden"
            hdr = (
                "HTTP/1.1 403 Forbidden\r\n"
                "Content-Type: text/html\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Connection: close\r\n\r\n"
            ).encode("utf-8")
            return hdr + body

        self.status_code = 200
        self.reason = "OK"
        self._header = self.build_response_header(request)
        return self._header + self._content