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
static inline bool ascii_frame_command(const char *line){
 if(strncmp(line,"FRAMEPROBE",10))return false;
 unsigned length,pad;char extra;
 if(sscanf(line,"FRAMEPROBE %u %u %c",&length,&pad,&extra)!=2||length<32||length>1024||pad>1){reply("ERR frame_args\n");return true;}
 char out[1026];int used=snprintf(out,sizeof(out),"FRAME1 {\"requested\":%u}",length);
 if(used<0||(unsigned)used>=length){reply("ERR frame_length\n");return true;}
 memset(out+used,' ',length-used);out[length-1]='\n';out[length]=0;
 size_t sent=pad?ascii_frame_pad(out,length,sizeof(out)):length;
 burst_serial_send(out,sent);return true;
}
