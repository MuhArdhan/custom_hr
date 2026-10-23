package com.customhr.checkin.prototype;

import static org.junit.Assert.assertEquals;
import static org.junit.Assert.assertThrows;
import org.junit.Test;

public class ServerUrlTest {
    @Test public void normalizesOriginAndHrmsPath() {
        assertEquals("https://example.com/hrms", ServerUrl.normalize(" https://EXAMPLE.com "));
        assertEquals("https://example.com/hrms", ServerUrl.normalize("https://example.com/hrms/"));
        assertEquals("https://example.com:8443/hrms", ServerUrl.normalize("https://example.com:8443/"));
    }

    @Test public void rejectsUnsafeOrUnexpectedUrls() {
        for (String url : new String[] {
            "http://example.com/hrms", "javascript:alert(1)", "https://user:password@example.com/hrms",
            "https://example.com/login", "https://example.com/hrms?token=x", "https://example.com/#x",
            "https://example.com:99999", "", "//example.com", "https://example.com/hrms%2F"
        }) {
            assertThrows(url, IllegalArgumentException.class, () -> ServerUrl.normalize(url));
        }
    }
}
