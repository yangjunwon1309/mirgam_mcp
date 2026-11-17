#include "netproto.h"
#include <esp_system.h>
#include <stdio.h>

String beaconNodeId() {
  const uint64_t mac = ESP.getEfuseMac();
  char id[10];
  snprintf(id, sizeof(id), "tc-%06lx", (unsigned long)(mac & 0xFFFFFFULL));
  return String(id);
}

static bool parseUInt(const String &s, uint32_t &value) {
  if (!s.length()) return false;
  uint64_t n = 0;
  for (size_t i = 0; i < s.length(); ++i) {
    if (s[i] < '0' || s[i] > '9') return false;
    n = n * 10 + (unsigned)(s[i] - '0');
    if (n > 0xFFFFFFFFULL) return false;
  }
  value = (uint32_t)n;
  return true;
}

BeaconResponse parseBeaconResponse(const String &body, uint32_t fallbackNext) {
  BeaconResponse out;
  out.nextSeconds = fallbackNext < 30 || fallbackNext > 15300 ? 300 : fallbackNext;
  uint32_t pendingNext = out.nextSeconds;
  int start = 0;
  String lastLine;
  while (start < (int)body.length()) {
    int end = body.indexOf('\n', start);
    if (end < 0) end = body.length();
    String line = body.substring(start, end);
    line.trim();
    start = end + 1;
    if (!line.length()) continue;
    lastLine = line;
    int eq = line.indexOf('=');
    if (eq < 0) continue;
    String key = line.substring(0, eq);
    String value = line.substring(eq + 1);
    if (key == "next") {
      uint32_t parsed;
      if (parseUInt(value, parsed)) pendingNext = constrain(parsed, 30U, 15300U);
    } else if (key == "tok" && value.length() <= 32) {
      out.token = value;
    } else if (key == "hold") {
      uint32_t parsed;
      if (parseUInt(value, parsed)) out.holdSeconds = (int)constrain(parsed, 0U, 180U);
    } else if (key == "cmd" && out.commandCount < 4) {
      BeaconCommand command;
      int space = value.indexOf(' ');
      if (space <= 0) continue;
      uint32_t id;
      if (!parseUInt(value.substring(0, space), id)) continue;
      command.id = id;
      String rest = value.substring(space + 1);
      rest.trim();
      int pos = rest.indexOf(' ');
      command.type = pos < 0 ? rest : rest.substring(0, pos);
      while (pos >= 0 && pos < (int)rest.length()) {
        int next = rest.indexOf(' ', pos + 1);
        String arg = rest.substring(pos + 1, next < 0 ? rest.length() : next);
        int aeq = arg.indexOf('=');
        if (aeq > 0) {
          String akey = arg.substring(0, aeq), avalue = arg.substring(aeq + 1);
          if (akey == "fs") command.fs = avalue;
          else if (akey == "q") command.q = avalue.toInt();
          else if (akey == "warm") command.warm = avalue.toInt();
          else if (akey == "fast") command.fast = avalue.toInt();
        }
        pos = next;
      }
      out.commands[out.commandCount++] = command;
    }
  }
  if (lastLine == "end") {
    out.complete = true;
    out.nextSeconds = pendingNext;
  } else {
    out.commandCount = 0;
    out.holdSeconds = 0;
    out.token = "";
  }
  return out;
}
