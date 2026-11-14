package com.ariousmeet.mcp;

/**
 * One {@code search_gifs} result.
 *
 * @param previewUrl a link on the server, valid for about an hour; null when the server gave none
 */
public record Gif(
    String gifId,
    String title,
    long width,
    long height,
    String contentType,
    String source,
    String previewUrl) {}
