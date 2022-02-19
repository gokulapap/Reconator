<!--
Documentation for Reconator
-->

<h1 align="center">
  <br>
  <a href="https://github.com/gokulapap/Reconator">
  <img src="./static/reconator.png" alt="reconator">
  </a>
  <br>
</h1>


<p align="center">
  <a href="https://github.com/gokulapap/Reconator">
    <img src="https://img.shields.io/badge/release-v1.0.0-green">
  </a>
   </a>
  <a href="https://www.gnu.org/licenses/gpl-3.0.en.html">
      <img src="https://img.shields.io/badge/license-GPL3-_red.svg">
  </a>
  <a href="https://twitter.com/CodingGokul">
    <img src="https://img.shields.io/badge/twitter-%40CodingGokul-blue">
  </a>
    <a href="https://github.com/gokulapap/Reconator/issues?q=is%3Aissue+is%3Aclosed">
    <img src="https://img.shields.io/github/issues-closed-raw/gokulapap/Reconator.svg">
  </a>
  <a href="https://github.com/gokulapap/Reconator/wiki">
    <img src="https://img.shields.io/badge/doc-wiki-blue.svg">
  </a>
  <a href="https://t.me/+cpbGih_iO50wNDg1">
    <img src="https://img.shields.io/badge/telegram-@Reconator-blue.svg">
  </a>
</p>

<h2 align="center">Summary</h2>
 

**Reconator** is a Framework for automating your process of reconnaisance without any Computing resource (Systemless Recon) at free of cost. Its Purely designed to host on Heroku which is a free cloud hosting provider. It performs the work of enumerations along with many vulnerability checks and obtains maximum information about the target domain.       

It also performs various vulnerability checks like XSS, Open Redirects, SSRF, CRLF, LFI, SQLi and much more. Along with these, it performs OSINT, fuzzing, dorking, ports scanning, nuclei scan on your target.

Reconator receives all the targets needs to be reconed via a Web Interface and adds into the Queue and Notifies via Telebot on start and end of Recon on a target. So this is 100% automated and don't require any manual interaction


# Deploy

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/gokulapap/reconator)

# Usage

**APPLICATION PATHS**
 
| path | Description |
|------|-------------|
| (/) home | Root page where you will add targets  |
| /initialise | Initialise the Database and the conjob |
| /queue | The targets added will be in the queue can manage targets |
| /scanned | It contains list of all scanned targets can view results by results |
| /issues | It has a quick link for reporting a issue and tool improvement |
 

## Features

<li> Database support permanent storage
<li> Fast scan and 100% Free
<li> Notification support via Telegram bot
<li> More...
  
# :fire: Features :fire:
 
 ## Osint
- Domain information parser ([domainbigdata](https://domainbigdata.com/))
- Emails addresses and users ([theHarvester](https://github.com/laramies/theHarvester), [emailfinder](https://github.com/Josue87/EmailFinder))
- Password leaks ([pwndb](https://github.com/davidtavarez/pwndb) and [H8mail](https://github.com/khast3x/h8mail))
- Metadata finder ([MetaFinder](https://github.com/Josue87/MetaFinder))
- Google Dorks ([uDork](https://github.com/m3n0sd0n4ld/uDork))
- Github Dorks ([GitDorker](https://github.com/obheda12/GitDorker))
## Subdomains
  - Passive ([subfinder](https://github.com/projectdiscovery/subfinder), [assetfinder](https://github.com/tomnomnom/assetfinder), [amass](https://github.com/OWASP/Amass), [findomain](https://github.com/Findomain/Findomain), [crobat](https://github.com/cgboal/sonarsearch), [waybackurls](https://github.com/tomnomnom/waybackurls), [github-subdomains](https://github.com/gwen001/github-subdomains), [Anubis](https://jldc.me), [gau](https://github.com/lc/gau))
  - Certificate transparency ([ctfr](https://github.com/UnaPibaGeek/ctfr), [tls.bufferover](tls.bufferover.run) and [dns.bufferover](dns.bufferover.run)))
  - Bruteforce ([puredns](https://github.com/d3mondev/puredns))
  - Permutations ([Gotator](https://github.com/Josue87/gotator))
  - JS files & Source Code Scraping ([gospider](https://github.com/jaeles-project/gospider))
  - DNS Records ([dnsx](https://github.com/projectdiscovery/dnsx))
  - Google Analytics ID ([AnalyticsRelationships](https://github.com/Josue87/AnalyticsRelationships))
  - Recursive search.
  - Subdomains takeover ([nuclei](https://github.com/projectdiscovery/nuclei))
  - DNS takeover ([dnstake](https://github.com/pwnesia/dnstake))
  - DNS Zone Transfer ([dnsrecon](https://github.com/darkoperator/dnsrecon))

## Hosts
- IP and subdomains WAF checker ([cf-check](https://github.com/dwisiswant0/cf-check) and [wafw00f](https://github.com/EnableSecurity/wafw00f))
- Port Scanner (Active with [nmap](https://github.com/nmap/nmap) and passive with [shodan-cli](https://cli.shodan.io/), Subdomains IP resolution with[resolveDomains](https://github.com/Josue87/resolveDomains))
- Port services vulnerability checks ([searchsploit](https://github.com/offensive-security/exploitdb))
- Password spraying ([brutespray](https://github.com/x90skysn3k/brutespray))
- Cloud providers check ([clouddetect](https://github.com/99designs/clouddetect))

## Webs
- Web Prober ([httpx](https://github.com/projectdiscovery/httpx) and [unimap](https://github.com/Edu4rdSHL/unimap))
- Web screenshot ([webscreenshot](https://github.com/maaaaz/webscreenshot) or [gowitness](https://github.com/sensepost/gowitness))
- Web templates scanner ([nuclei](https://github.com/projectdiscovery/nuclei) and [nuclei geeknik](https://github.com/geeknik/the-nuclei-templates.git))
- Url extraction ([waybackurls](https://github.com/tomnomnom/waybackurls), [gauplus](https://github.com/bp0lr/gauplus), [gospider](https://github.com/jaeles-project/gospider), [github-endpoints](https://gist.github.com/six2dez/d1d516b606557526e9a78d7dd49cacd3) and [JSA](https://github.com/w9w/JSA))
- URLPatterns Search ([gf](https://github.com/tomnomnom/gf) and [gf-patterns](https://github.com/1ndianl33t/Gf-Patterns))
- XSS ([dalfox](https://github.com/hahwul/dalfox))
- Open redirect ([Oralyzer](https://github.com/r0075h3ll/Oralyzer))
- SSRF (headers [interactsh](https://github.com/projectdiscovery/interactsh) and param values with [ffuf](https://github.com/ffuf/ffuf))
- CRLF ([crlfuzz](https://github.com/dwisiswant0/crlfuzz))
- Favicon Real IP ([fav-up](https://github.com/pielco11/fav-up))
- Javascript analysis ([subjs](https://github.com/lc/subjs), [JSA](https://github.com/w9w/JSA), [LinkFinder](https://github.com/GerbenJavado/LinkFinder), [getjswords](https://github.com/m4ll0k/BBTz))
- Fuzzing ([ffuf](https://github.com/ffuf/ffuf))
- Cors ([Corsy](https://github.com/s0md3v/Corsy))
- LFI Checks ([ffuf](https://github.com/ffuf/ffuf))
- SQLi Check ([SQLMap](https://github.com/sqlmapproject/sqlmap))
- SSTI ([ffuf](https://github.com/ffuf/ffuf))
- CMS Scanner ([CMSeeK](https://github.com/Tuhinshubhra/CMSeeK))
- SSL tests ([testssl](https://github.com/drwetter/testssl.sh))
- Broken Links Checker ([gospider](https://github.com/jaeles-project/gospider))
- S3 bucket finder ([S3Scanner](https://github.com/sa7mon/S3Scanner))
- Prototype Pollution ([ppfuzz](https://github.com/dwisiswant0/ppfuzz))
- URL sorting by extension
- Wordlist generation
- Passwords dictionary creation ([pydictor](https://github.com/LandGrey/pydictor))

<hr> 
  
## Helping hands 🤝

 - <a href="https://github.com/jopraveen">Jopraveen</a> (Video Editing & FrontEnd)
 - <a href="https://github.com/santhasarooban">Santroo</a> (FrontEnd design)
 - <a href="https://github.com/0xGodson">Godson</a> (Script Searching)
 - <a href="https://github.com/venom33cm">Yashwant</a> (FrontEnd design)
  
## How to contribute:
 
If you want to contribute to this project then:
- Submitting an [issue](https://github.com/gokulapap/Reconator/issues/new/choose) because you have found a bug or you have any suggestion or request.
- Submitting a feature request in this Form [form](https://forms.gle/VaZ9e4QTBxhjk2At7)
 
## Need help? :information_source:
 
- Take a look at the [wiki](https://github.com/six2dez/reconftw/wiki) section.  
- Check [FAQ](https://github.com/six2dez/reconftw/wiki/7.-FAQs) for commonly asked questions.  
- Ask for help in the [Telegram group](https://t.me/joinchat/TO_R8NYFhhbmI5co)
  
## Disclaimer
Usage of this program for attacking targets without consent is illegal. It is the user's responsibility to obey all applicable laws. The developer assumes no liability and is not responsible for any misuse or damage caused by this program. Please use responsibly.

The material contained in this repository is licensed under GNU GPLv3.

