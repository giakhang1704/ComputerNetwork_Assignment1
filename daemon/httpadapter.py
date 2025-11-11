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
daemon.httpadapter
~~~~~~~~~~~~~~~~~

This module provides a http adapter object to manage and persist 
http settings (headers, bodies). The adapter supports both
raw URL paths and RESTful route definitions, and integrates with
Request and Response objects to handle client-server communication.
"""

import json
from .request import Request
from .response import Response
from .dictionary import CaseInsensitiveDict

class HttpAdapter:
    """
    A mutable :class:`HTTP adapter <HTTP adapter>` for managing client connections
    and routing requests.

    The `HttpAdapter` class encapsulates the logic for receiving HTTP requests,
    dispatching them to appropriate route handlers, and constructing responses.
    It supports RESTful routing via hooks and integrates with :class:`Request <Request>` 
    and :class:`Response <Response>` objects for full request lifecycle management.

    Attributes:
        ip (str): IP address of the client.
        port (int): Port number of the client.
        conn (socket): Active socket connection.
        connaddr (tuple): Address of the connected client.
        routes (dict): Mapping of route paths to handler functions.
        request (Request): Request object for parsing incoming data.
        response (Response): Response object for building and sending replies.
    """

    __attrs__ = [
        "ip",
        "port",
        "conn",
        "connaddr",
        "routes",
        "request",
        "response",
    ]

    def __init__(self, ip, port, conn, connaddr, routes):
        """
        Initialize a new HttpAdapter instance.

        :param ip (str): IP address of the client.
        :param port (int): Port number of the client.
        :param conn (socket): Active socket connection.
        :param connaddr (tuple): Address of the connected client.
        :param routes (dict): Mapping of route paths to handler functions.
        """

        #: IP address.
        self.ip = ip
        #: Port.
        self.port = port
        #: Connection
        self.conn = conn
        #: Conndection address
        self.connaddr = connaddr
        #: Routes
        self.routes = routes
        #: Request
        self.request = Request()
        #: Response
        self.response = Response()
        
    def _recv_full_http(self, conn):
        data = b""
        conn.settimeout(2.0)
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\r\n\r\n" in data:
                head, body = data.split(b"\r\n\r\n", 1)
                headers = head.decode(errors="ignore").split("\r\n")
                cl = None
                for line in headers:
                    if line.lower().startswith("content-length:"):
                        try:
                            cl = int(line.split(":", 1)[1].strip())
                        except:
                            cl = None
                        break
                if cl is None or len(body) >= cl:
                    break
        return data.decode(errors="ignore")


    def handle_client(self, conn, addr, routes):
        """
        Handle an incoming client connection.

        This method reads the request from the socket, prepares the request object,
        invokes the appropriate route handler if available, builds the response,
        and sends it back to the client.

        :param conn (socket): The client socket connection.
        :param addr (tuple): The client's address.
        :param routes (dict): The route mapping for dispatching requests.
        """
        self.conn = conn        

        self.connaddr = addr

        req = self.request

        resp = self.response

        try:
            raw = self._recv_full_http(conn)
            print(f"[HttpAdapter] Received request from {addr}")

            req.prepare(raw, routes)
            path = req.path or "/"
            method = (req.method or "GET").upper()
            is_public = (
                (method, path) == ("POST", "/login")
                or path.endswith((".html", ".css", ".js", ".png", ".jpg", ".ico"))
                or path == "/"  
            )

            if not is_public:
                ck = (req.headers or {}).get("cookie", "")
                if "auth=true" not in ck:
                    resp.status_code = 401
                    resp.headers["Content-Type"] = "application/json"
                    resp.body = json.dumps({"ok": False, "error": "Unauthorized"})
                    conn.sendall(resp.build_response(req))
                    conn.close()
                    return
            print(f"[HttpAdapter] Method: {getattr(req,'method','UNKNOWN')}, Path: {getattr(req,'path','UNKNOWN')}")

            if req.hook:
                print(f"[HttpAdapter] Hook found - METHOD {getattr(req.hook,'_route_methods',None)} PATH {getattr(req.hook,'_route_path',None)}")
                try:
                    result = req.hook(headers=req.headers, body=req.body or "")
                    if isinstance(result, (dict, list)):
                        req.hook_response = result
                    elif isinstance(result, (str, bytes)):
                        req.hook_response = {
                            "message": result if isinstance(result, str)
                            else result.decode("utf-8", "ignore")
                        }
                    else:
                        req.hook_response = {"ok": True}
                except Exception as e:
                    import traceback; traceback.print_exc()
                    req.hook_response = {"error": str(e)}
            else:
                print("[HttpAdapter] No hook found for this request")

            # Build and send response
            response_bytes = resp.build_response(req)
            conn.sendall(response_bytes)

        except Exception:
            import traceback; traceback.print_exc()
            try:
                conn.sendall(
                    b"HTTP/1.1 500 Internal Server Error\r\n"
                    b"Content-Type: text/plain\r\n\r\n"
                    b"Internal Server Error"
                )
            except:
                pass
        finally:
            try:
                conn.close()
            except:
                pass

    def extract_cookies(self, req):
        """
        Build cookies from the :class:`Request <Request>` headers.

        :param req:(Request) The :class:`Request <Request>` object.
        :param resp: (Response) The res:class:`Response <Response>` object.
        :rtype: cookies - A dictionary of cookie key-value pairs.
        """
        cookies = {}
        headers = getattr(req, "headers", {}) or {}
        cookie_str = headers.get("cookie")
        
        if not cookie_str:
            return cookies
        
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if "=" in pair:
                key, value = pair.split("=", 1)
                cookies[key] = value
        return cookies

    def build_response(self, req, resp):
        """Builds a :class:`Response <Response>` object 

        :param req: The :class:`Request <Request>` used to generate the response.
        :param resp: The  response object.
        :rtype: Response
        """
        response = Response()

        # Set encoding.
        response.encoding = self.get_encoding_from_headers(response.headers)
        response.raw = resp
        response.reason = response.raw.reason

        if isinstance(req.url, bytes):
            response.url = req.url.decode("utf-8")
        else:
            response.url = req.url

        # Add new cookies from the server.
        response.cookies = self.extract_cookies(req)

        # Give the Response some context.
        response.request = req
        response.connection = self

        return response

    # def get_connection(self, url, proxies=None):
        # """Returns a url connection for the given URL. 

        # :param url: The URL to connect to.
        # :param proxies: (optional) A Requests-style dictionary of proxies used on this request.
        # :rtype: int
        # """

        # proxy = select_proxy(url, proxies)

        # if proxy:
            # proxy = prepend_scheme_if_needed(proxy, "http")
            # proxy_url = parse_url(proxy)
            # if not proxy_url.host:
                # raise InvalidProxyURL(
                    # "Please check proxy URL. It is malformed "
                    # "and could be missing the host."
                # )
            # proxy_manager = self.proxy_manager_for(proxy)
            # conn = proxy_manager.connection_from_url(url)
        # else:
            # # Only scheme should be lower case
            # parsed = urlparse(url)
            # url = parsed.geturl()
            # conn = self.poolmanager.connection_from_url(url)

        # return conn


    def add_headers(self, request):
        """
        Add headers to the request.

        This method is intended to be overridden by subclasses to inject
        custom headers. It does nothing by default.

        
        :param request: :class:`Request <Request>` to add headers to.
        """
        pass

    def build_proxy_headers(self, proxy):
        """Returns a dictionary of the headers to add to any request sent
        through a proxy. 

        :class:`HttpAdapter <HttpAdapter>`.

        :param proxy: The url of the proxy being used for this request.
        :rtype: dict
        """
        headers = {}
        #
        # TODO: build your authentication here
        #       username, password =...
        # we provide dummy auth here
        #
        username, password = ("admin", "password")

        if username:
            headers["Proxy-Authorization"] = (username, password)

        return headers