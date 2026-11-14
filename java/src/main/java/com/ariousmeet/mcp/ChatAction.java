package com.ariousmeet.mcp;

import com.fasterxml.jackson.annotation.JsonValue;

/**
 * What the agent is doing, for {@code sendChatAction} and {@code sendTyping(conversationId, action)}.
 * The notice fades after about 5 seconds: repeat it about every 4 seconds while the work goes on.
 * {@link #CANCEL} clears it at once.
 */
public enum ChatAction {
  TYPING("typing"),
  UPLOAD_PHOTO("upload_photo"),
  UPLOAD_VIDEO("upload_video"),
  RECORD_VOICE("record_voice"),
  UPLOAD_VOICE("upload_voice"),
  UPLOAD_DOCUMENT("upload_document"),
  RECORD_VIDEO_NOTE("record_video_note"),
  UPLOAD_VIDEO_NOTE("upload_video_note"),
  CHOOSE_STICKER("choose_sticker"),
  FIND_LOCATION("find_location"),
  CANCEL("cancel");

  private final String wire;

  ChatAction(String wire) {
    this.wire = wire;
  }

  /** The name the server uses ({@code upload_photo}...). */
  @JsonValue
  public String wire() {
    return wire;
  }
}
