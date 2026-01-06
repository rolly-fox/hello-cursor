"""
NetBox API client with caching support.

Read-only client that fetches and caches rack/device data for validation.
"""

import os
from typing import Optional
from datetime import datetime

import requests
import yaml

from .models import NetBoxCache, CachedRack, CachedDevice


class NetBoxClientError(Exception):
    """Exception raised for NetBox API errors."""
    pass


class NetBoxClient:
    """Read-only NetBox API client with caching."""

    def __init__(self, url: str = "", token: str = "", site: str = "", verify_ssl: bool = True):
        self.url = url.rstrip("/")
        self.token = token
        self.site_identifier = site  # Can be slug (string) or ID (numeric string)
        self.verify_ssl = verify_ssl
        self.cache = NetBoxCache()
        self.cache_timestamp: Optional[datetime] = None
        self._session = requests.Session()
        
        # Disable SSL warnings if verification is disabled
        if not verify_ssl:
            import urllib3
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    @property
    def site_slug(self) -> str:
        """Backward compatibility property."""
        return self.site_identifier

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "NetBoxClient":
        """Create client from config file, with environment variable overrides."""
        config = {}
        
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                config = yaml.safe_load(f) or {}

        netbox_config = config.get("netbox", {})
        
        # Environment variables override config file
        url = os.environ.get("NETBOX_URL", netbox_config.get("url", ""))
        token = os.environ.get("NETBOX_TOKEN", netbox_config.get("token", ""))
        site = os.environ.get("NETBOX_SITE", netbox_config.get("site", ""))
        verify_ssl = netbox_config.get("verify_ssl", True)

        return cls(url=url, token=token, site=site, verify_ssl=verify_ssl)

    @property
    def headers(self) -> dict:
        """HTTP headers for API requests."""
        return {
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        """Check if client has required configuration."""
        return bool(self.url and self.token)

    @property
    def cache_age_seconds(self) -> Optional[float]:
        """Returns age of cache in seconds, or None if not cached."""
        if self.cache_timestamp is None:
            return None
        return (datetime.now() - self.cache_timestamp).total_seconds()

    def _get(self, endpoint: str, params: Optional[dict] = None) -> dict:
        """Make GET request to NetBox API."""
        if not self.is_configured:
            raise NetBoxClientError("NetBox client not configured (missing URL or token)")

        url = f"{self.url}/api/{endpoint}"
        
        try:
            response = self._session.get(url, headers=self.headers, params=params, timeout=30, verify=self.verify_ssl)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise NetBoxClientError(f"Request timed out: {url}")
        except requests.exceptions.ConnectionError as e:
            raise NetBoxClientError(f"Connection failed: {e}")
        except requests.exceptions.HTTPError as e:
            raise NetBoxClientError(f"HTTP error {response.status_code}: {response.text}")

    def _get_all(self, endpoint: str, params: Optional[dict] = None) -> list:
        """Fetch all pages of a paginated endpoint."""
        results = []
        params = params or {}
        params["limit"] = 1000  # Max per page
        
        while True:
            data = self._get(endpoint, params)
            results.extend(data.get("results", []))
            
            if not data.get("next"):
                break
            
            # Parse offset from next URL
            next_url = data["next"]
            if "offset=" in next_url:
                offset = int(next_url.split("offset=")[1].split("&")[0])
                params["offset"] = offset
            else:
                break

        return results

    def test_connection(self) -> tuple[bool, str]:
        """Test connection to NetBox. Returns (success, message)."""
        try:
            data = self._get("status/")
            version = data.get("netbox-version", "unknown")
            return True, f"Connected to NetBox {version}"
        except NetBoxClientError as e:
            return False, str(e)

    def get_site_id(self) -> Optional[int]:
        """Fetch site ID for configured site slug."""
        if not self.site_slug:
            return None
        
        try:
            data = self._get("dcim/sites/", {"slug": self.site_slug})
            results = data.get("results", [])
            if results:
                return results[0]["id"]
        except NetBoxClientError:
            pass
        
        return None

    def refresh_cache(self, site_identifier: Optional[str] = None) -> int:
        """
        Refresh cache with data from NetBox.
        
        Args:
            site_identifier: Site slug or ID. Uses configured site if not provided.
            
        Returns:
            Number of racks cached.
            
        Raises:
            NetBoxClientError: If site not found or API error.
        """
        site_identifier = site_identifier or self.site_identifier
        if not site_identifier:
            raise NetBoxClientError("No site specified")

        # Clear existing cache
        self.cache.clear()

        # Determine if identifier is an ID (numeric) or slug (string)
        site = None
        if site_identifier.isdigit():
            # It's a numeric ID - fetch directly
            try:
                site = self._get(f"dcim/sites/{site_identifier}/")
            except NetBoxClientError:
                pass
        
        if site is None:
            # Try as slug
            sites = self._get("dcim/sites/", {"slug": site_identifier})
            site_results = sites.get("results", [])
            if site_results:
                site = site_results[0]
        
        if site is None:
            raise NetBoxClientError(f"Site not found: {site_identifier}")
        
        site = site_results[0]
        self.cache.site_id = site["id"]
        self.cache.site_name = site["name"]

        # Fetch all racks for this site
        racks = self._get_all("dcim/racks/", {"site_id": self.cache.site_id})
        for rack_data in racks:
            rack = CachedRack(
                id=rack_data["id"],
                name=rack_data["name"],
                site_id=self.cache.site_id,
                site_name=self.cache.site_name,
                location_id=rack_data.get("location", {}).get("id") if rack_data.get("location") else None,
                location_name=rack_data.get("location", {}).get("name") if rack_data.get("location") else None,
                u_height=rack_data.get("u_height", 42),
            )
            self.cache.add_rack(rack)

        # Fetch all devices for this site
        devices = self._get_all("dcim/devices/", {"site_id": self.cache.site_id})
        for dev_data in devices:
            device = CachedDevice(
                id=dev_data["id"],
                name=dev_data["name"],
                rack_id=dev_data.get("rack", {}).get("id") if dev_data.get("rack") else None,
                rack_name=dev_data.get("rack", {}).get("name") if dev_data.get("rack") else None,
                position=dev_data.get("position"),
                u_height=dev_data.get("device_type", {}).get("u_height", 1) if dev_data.get("device_type") else 1,
                device_type=dev_data.get("device_type", {}).get("model") if dev_data.get("device_type") else None,
                manufacturer=dev_data.get("device_type", {}).get("manufacturer", {}).get("name") if dev_data.get("device_type") else None,
            )
            self.cache.add_device(device)

        self.cache_timestamp = datetime.now()
        return len(self.cache.racks)

    def get_rack_names(self) -> list[str]:
        """Get list of cached rack names."""
        return list(self.cache.racks.keys())

    def get_device_count(self) -> int:
        """Get count of cached devices."""
        return len(self.cache.devices)
