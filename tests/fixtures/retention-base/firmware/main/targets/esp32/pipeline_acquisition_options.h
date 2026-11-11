#pragma once
/* Existing PIPEKERNEL selects energy; these select complete acquisition stages. */
static bool pipeline_acquisition_options_command(const char *line){
    unsigned value;char extra;
    if(!strcmp(line,"ACQOPT?")){reply("ACQOPT %u\n",acquisition_option);return true;}
    if(!strcmp(line,"CLEAROPT?")){reply("CLEAROPT %u\n",clear_option);return true;}
    if(!strncmp(line,"ACQOPT",6)){
        if(sscanf(line,"ACQOPT %u %c",&value,&extra)==1 && value<=3){acquisition_option=value;reply("OK\n");}
        else reply("ERR acquisition_option\n");
        return true;
    }
    if(!strncmp(line,"CLEAROPT",8)){
        if(sscanf(line,"CLEAROPT %u %c",&value,&extra)==1 && value<=1){clear_option=value;reply("OK\n");}
        else reply("ERR clear_option\n");
        return true;
    }
    return false;
}
