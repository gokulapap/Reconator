from dataclasses import dataclass


@dataclass(frozen=True)
class ModuleSpec:
    name: str
    description: str
    argv: tuple[str, ...]
    timeout: int = 1800


MODULES: list[ModuleSpec] = [
    ModuleSpec("index", "Result index header", ("modules/index.sh", "{url}")),
    ModuleSpec("dnscan", "DNS enumeration", ("modules/dnscan.sh", "{url}"), 600),
    ModuleSpec(
        "clickjacking", "Clickjacking probe", ("python", "modules/clickjacking", "{url}"), 300
    ),
    ModuleSpec("corstest", "CORS misconfig test", ("python", "modules/corstest", "{url}"), 600),
    ModuleSpec("firewall", "WAF detection", ("modules/firewall.sh", "{url}"), 300),
    ModuleSpec("davtest", "WebDAV testing", ("modules/davtest.sh", "{url}"), 600),
    ModuleSpec("robots", "robots.txt analysis", ("modules/robots.sh", "{url}"), 120),
    ModuleSpec("subdomains", "Subdomain enumeration", ("modules/subdomains.sh", "{url}"), 1800),
    ModuleSpec("dirb", "Directory brute force", ("modules/dirb.sh", "{url}"), 1800),
    ModuleSpec("js-finder", "JS / link finder", ("modules/js-finder.sh", "{url}"), 900),
    ModuleSpec("subtake", "Subdomain takeover check", ("modules/subtake.sh", "{url}"), 600),
    ModuleSpec(
        "sub_title_cname", "Subdomain titles + CNAMEs", ("modules/sub_title_cname.sh", "{url}"), 900
    ),
    ModuleSpec(
        "sub_ip_server", "Subdomain IPs + servers", ("modules/sub_ip_server.sh", "{url}"), 900
    ),
    ModuleSpec("whois", "WHOIS lookup", ("modules/whois.sh", "{url}"), 120),
    ModuleSpec("shcheck", "Security headers check", ("modules/shcheck.sh", "{url}"), 300),
    ModuleSpec("wappy", "Tech fingerprint (Wappalyzer)", ("modules/wappy.sh", "{url}"), 300),
    ModuleSpec("gather_urls", "URL gathering", ("modules/gather_urls.sh", "{url}"), 1800),
    ModuleSpec("gf_patterns", "GF pattern triage", ("modules/gf_patterns.sh", "{url}"), 900),
]


def get_module(name: str) -> ModuleSpec | None:
    for m in MODULES:
        if m.name == name:
            return m
    return None
