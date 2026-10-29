# Artifact downloads

The canonical download is `GET /api/v1/files/{id}/download`. PrintStash checks
current access before serving bytes, validating a browser's cached response or
issuing a temporary provider redirect. The old `download-url` and
`download-direct` endpoints have been removed.

Local originals use the file response, including ranges and `If-Range`. Managed
S3 originals and stored thumbnails can use a short-lived HTTPS GET URL when the
provider can preserve the filename and support the browser request. Other
transports, external Library Sources, generated previews, public shares and
slicer capabilities retain API delivery. External content is verified before
exposure. Redirect URLs are bearer credentials; they are not persisted.

Authenticated originals and thumbnails use `private, max-age=0, must-revalidate`.
Shares and slicer responses use `private, no-store`. Original validators use
SHA-256; converted content uses its own representation validator. ETag conditions
take precedence over modification dates. Requests with Range retain API delivery because the provider ETag can differ
from the original SHA-256. S3 proxy reads support one byte range;
unsupported multi-range syntax falls back to the full representation.

## Browser configuration

Native delivery for browser `fetch` requests requires the bucket owner to add a
CORS rule. PrintStash validates that rule but does not create or modify bucket
CORS configuration; without it, downloads safely fall back to API proxying.

The app downloads with authenticated `fetch`. A provider redirect therefore needs
CORS, even for the ordinary Download action. PrintStash reads the bucket's CORS
configuration; absence of this capability or permission keeps delivery through
the API. It does not change bucket configuration. The S3 endpoint must also use
a different origin from PrintStash so an application `Authorization` header can
never be retained across the redirect.

Allow the actual PrintStash origin and expose `Content-Disposition`. For example:

```json
{
  "CORSRules": [{
    "AllowedOrigins": ["https://printstash.example.com"],
    "AllowedMethods": ["GET", "HEAD"],
    "AllowedHeaders": ["*"],
    "ExposeHeaders": ["Content-Disposition"]
  }]
}
```

The origin, method and request headers must match the provider's CORS rule;
object authorization still applies. See [S3 CORS behavior](https://docs.aws.amazon.com/AmazonS3/latest/userguide/cors.html).
The first matching rule must expose the filename. PrintStash conservatively
requires permission for conditional and range headers as well as cache-control
headers before redirecting a browser fetch.

A signed GET expires after at most 60 seconds, also capped by
`VAULT_S3_PRESIGNED_URL_EXPIRE_SECONDS`. Redirect responses are private/no-store
and use `Referrer-Policy: no-referrer`. The client retries a failed provider
response once against the original API URL with `X-PrintStash-Delivery: proxy`.
This repeats authorization and never sends the application bearer token to a
provider URL manually. Browser downloads still assemble a Blob before saving;
this change removes API body transit, not browser memory usage.

Cloudflare R2 uses its existing S3 API endpoint. Its [presigned URLs](https://developers.cloudflare.com/r2/api/s3/presigned-urls/)
provide temporary object access. This feature does not add CDN caching, custom
domains, Workers or a separate delivery adapter.

## Operational diagnostics

Detailed health reports the configured delivery mode and whether native delivery
is a candidate, without signing an object URL. Browser CORS is still checked per
request. `printstash_delivery_strategy_total` counts selected strategies and
`printstash_delivery_proxied_bytes_total` counts consumed proxy bytes. Labels are
restricted to bounded provider and purpose values; they contain no keys, user
identities or signed destinations. Telemetry failure does not fail a download.
Application and Uvicorn access/error logs redact URL queries, including SDK
exception text. Deployment proxies must likewise avoid recording response
`Location` headers.

An already issued URL remains usable until its short expiry even if access is
revoked immediately afterward. Every subsequent API request repeats authorization.
Thumbnails retain inline disposition; ordinary downloads retain attachment
disposition, with the same filename sanitization in API and signed responses.
