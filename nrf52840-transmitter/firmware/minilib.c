/* Minimal freestanding routines; printf supports only %s, %d, %lu used here. */
#include <stddef.h>
#include <stdarg.h>
void *memcpy(void *d,const void *s,size_t n){unsigned char *a=d;const unsigned char *b=s;while(n--)*a++=*b++;return d;}
void *memset(void *d,int c,size_t n){unsigned char *a=d;while(n--)*a++=c;return d;}
size_t strlen(const char *s){const char *p=s;while(*p)p++;return p-s;}
int strcmp(const char*a,const char*b){while(*a&&*a==*b){a++;b++;}return (unsigned char)*a-(unsigned char)*b;}
int strncmp(const char*a,const char*b,size_t n){while(n&&*a&&*a==*b){a++;b++;n--;}return n?(unsigned char)*a-(unsigned char)*b:0;}
char *strchr(const char*s,int c){do{if(*s==c)return (char*)s;}while(*s++);return NULL;}
char *strtok(char *s,const char *del){static char *p;if(s)p=s;if(!p)return NULL;while(*p&&strchr(del,*p))p++;if(!*p)return NULL;s=p;while(*p&&!strchr(del,*p))p++;if(*p)*p++=0;return s;}
static void put(char *s,size_t cap,size_t *n,char c){if(*n+1<cap)s[*n]=c;(*n)++;}
int snprintf(char *s,size_t cap,const char *fmt,...){va_list ap;va_start(ap,fmt);size_t n=0;while(*fmt){if(*fmt!='%'){put(s,cap,&n,*fmt++);continue;}fmt++;int lng=0;if(*fmt=='l'){lng=1;fmt++;}char f=*fmt++;if(f=='s'){const char*p=va_arg(ap,const char*);while(*p)put(s,cap,&n,*p++);}else{unsigned long v;if(f=='d'){int x=va_arg(ap,int);if(x<0){put(s,cap,&n,'-');v=(unsigned)(-x);}else v=x;}else v=lng?va_arg(ap,unsigned long):va_arg(ap,unsigned int);char b[12];unsigned k=0;do{b[k++]='0'+v%10;v/=10;}while(v);while(k)put(s,cap,&n,b[--k]);}}va_end(ap);if(cap)s[n<cap?n:cap-1]=0;return n;}
