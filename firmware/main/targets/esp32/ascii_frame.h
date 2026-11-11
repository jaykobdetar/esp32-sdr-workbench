#pragma once
/* Experimental CP2102 framing workaround, ASCII JSON lines ONLY.
 * Never call on DATA headers or binary payloads. Keep exactly one newline. */
static inline size_t ascii_frame_pad(char *line,size_t length,size_t capacity){
 if(!length||length>=capacity||line[length-1]!='\n')return 0;
 if(length%64==0){
  if(length+1>=capacity)return 0;
  line[length-1]=' ';line[length]='\n';line[++length]=0;
 }
 return length;
}
