package com.customhr.checkin.prototype;

import java.net.URI;
import java.net.URISyntaxException;
import java.util.Locale;

/** Shared validation for saved URLs and the native recovery form. */
public final class ServerUrl {
    private ServerUrl() {}

    public static String normalize(String value) {
        try {
            URI uri = new URI(value.trim());
            String host = uri.getHost();
            String path = uri.getRawPath();
            if (!"https".equalsIgnoreCase(uri.getScheme()) || host == null ||
                uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null ||
                (uri.getPort() != -1 && (uri.getPort() < 1 || uri.getPort() > 65535)) ||
                !(path == null || path.isEmpty() || path.equals("/") || path.equals("/hrms") || path.equals("/hrms/"))) {
                throw new IllegalArgumentException();
            }
            return new URI("https", null, host.toLowerCase(Locale.ROOT), uri.getPort(), "/hrms", null, null).toASCIIString();
        } catch (URISyntaxException | IllegalArgumentException | NullPointerException exception) {
            throw new IllegalArgumentException("Masukkan URL HTTPS server HRMS tanpa kredensial, query, atau path selain /hrms.");
        }
    }
}
