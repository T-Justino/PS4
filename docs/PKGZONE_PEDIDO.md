# Rascunho de pedido ao PKG-Zone (para VOCÊ enviar, se quiser)

O contato público está nos Termos do site: Darksoftware LLC, `seth@darksoftware.xyz` (https://pkg-zone.com/page/terms-of-service). **Nada foi enviado.**

> **Subject:** Permission to read the public catalog and list direct links (SSPI catalog project)
>
> Hello,
>
> I'm building a small open-source tool that generates package-source files for the SSPI installer on jailbroken PS4s. It would read
> `https://pkg-zone.com/api/v1/catalog` (the same public JSON the site loads) at low frequency (a few times a day, one request each),
> and, for new releases, fetch only the first 64 KB of the download link (HTTP Range) to read the PKG header. Nothing is hosted or mirrored by us;
> the console would download directly from pkg-zone.com.
>
> Could you confirm:
> 1. Is this kind of automated, low-volume access to the catalog acceptable? Is there a preferred way (an official feed, an ETag/`If-Modified-Since`, a rate limit)?
> 2. Do partial `Range` requests to `/download/ps4/{titleId}/{version}` count in the download statistics? Is there a HEAD-friendly or non-counting alternative?
> 3. May we list direct links to apps in our catalog? We understand each app's license belongs to its author; we would list only apps whose author/license allows it. Is there a license field we can read?
> 4. The download link redirects (302) to a signed URL on `api.pkg-zone.com` that expires. Is that redirect expected to work from a console HTTP client, and is the `/download/...` link stable?
>
> Thanks,
> (name / project link)
