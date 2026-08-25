# Third-party tools

The Reconator toolbox image installs pinned versions of independently maintained
open-source projects. Reconator invokes them as replaceable capability
implementations and ships their compiled, unmodified command binaries. Exact upstream
license texts are preserved in `/usr/share/licenses/reconator-toolbox` in the image.

| Tool | Pin | Upstream | License |
| --- | --- | --- | --- |
| Subfinder | v2.16.0 | https://github.com/projectdiscovery/subfinder | MIT |
| URLFinder | v0.0.3 | https://github.com/projectdiscovery/urlfinder | MIT |
| httpx | v1.10.0 | https://github.com/projectdiscovery/httpx | MIT |
| Katana | v1.7.0 | https://github.com/projectdiscovery/katana | MIT |
| Naabu | v2.6.1 | https://github.com/projectdiscovery/naabu | MIT |
| jsluice | 0ddfab153e060a9eeaded4d8669233f7c071e7e4 | https://github.com/BishopFox/jsluice | MIT |
| AlterX | v0.1.0 | https://github.com/projectdiscovery/alterx | MIT |
| CDNCheck | v1.2.50 | https://github.com/projectdiscovery/cdncheck | MIT |

Review each linked upstream license before redistributing a toolbox image. The
version pins are intentionally explicit so dependency updates can be reviewed,
rebuilt and regression-tested rather than changing at container start-up.
