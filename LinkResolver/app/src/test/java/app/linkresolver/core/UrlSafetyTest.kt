package app.linkresolver.core

import org.junit.Assert.*
import org.junit.Test

class UrlSafetyTest {
    private fun ok(u: String) = assertTrue("deveria aceitar $u", UrlSafety.check(u) is UrlSafety.Verdict.Ok)
    private fun bad(u: String) = assertTrue("deveria recusar $u", UrlSafety.check(u) is UrlSafety.Verdict.Rejected)

    @Test fun acceptsPublicHttps() {
        ok("https://example.com/download?id=1")
        ok("https://cdn.exemplo.com.br:8443/a.zip")
        ok("https://8.8.8.8/file.zip")
    }

    @Test fun rejectsDangerousSchemes() {
        listOf("javascript:alert(1)", "file:///etc/passwd", "content://x/y", "intent://x#Intent;end",
            "data:text/html,hi", "ftp://a.com/x", "market://details?id=a", "http://example.com/").forEach { bad(it) }
    }

    @Test fun rejectsLocalAndInternal() {
        listOf(
            "https://localhost/", "https://foo.localhost/", "https://127.0.0.1/", "https://10.0.0.5/",
            "https://192.168.1.1/", "https://172.16.0.1/", "https://172.31.255.255/", "https://169.254.169.254/latest",
            "https://100.64.0.1/", "https://0.0.0.0/", "https://2130706433/", "https://0x7f.0.0.1/",
            "https://0177.0.0.1/", "https://127.1/", "https://[::1]/", "https://[fe80::1]/",
            "https://router.local/", "https://intranet/", "https://metadata.google.internal/",
            "https://127.0.0.1.nip.io/", "https://user:pw@example.com/", "https://example.com:99999/",
        ).forEach { bad(it) }
    }

    @Test fun ipv4Forms() {
        assertArrayEquals(intArrayOf(127, 0, 0, 1), UrlSafety.parseIpv4("2130706433"))
        assertArrayEquals(intArrayOf(127, 0, 0, 1), UrlSafety.parseIpv4("0x7f.1"))
        assertNull(UrlSafety.parseIpv4("1.2.3.256"))
        assertFalse(UrlSafety.isPrivateIpv4(intArrayOf(8, 8, 8, 8)))
        assertFalse(UrlSafety.isPrivateIpv4(intArrayOf(172, 32, 0, 1)))
    }

    @Test fun redactsSensitiveData() {
        val r = UrlSafety.redact("https://u:p@host.com/f.zip?token=abc123&id=7&X-Amz-Signature=zzz#access_token=q")
        assertFalse(r.contains("abc123")); assertFalse(r.contains("zzz")); assertFalse(r.contains("u:p"))
        assertFalse(r.contains("access_token"))
        assertTrue(r.contains("id=7"))
        assertTrue(UrlSafety.hasSensitiveParams("https://h.com/f?token=1"))
        assertFalse(UrlSafety.hasSensitiveParams("https://h.com/f?id=1"))
    }

    @Test fun loopKeyNormalizes() {
        assertEquals(UrlSafety.loopKey("https://a.com/x/?b=2&a=1#frag"), UrlSafety.loopKey("https://A.com/x?a=1&b=2"))
    }
}
