baidupcs-go任务管理，主要功能：  
    添加任务，支持同时添加多个下载任务  
    任务暂停/恢复，自动恢复未完成的下载任务  
    任务进度追踪检查，列出正在下载的任务进度，下载完成的任务自动校验md5  
    任务删除/还原/清理，清理未完成的下载任务，同时删除关联的文件  
    以守护进程运行，baidupcs挂掉时自动重启进程  
  
Usage: baidudld [ option ] command  
    option:  
    --daemon: run as daemon  
    --verbose: write baidupcs output to file  
    command: [ start | stop | resume | list | remove | restore | clean | login-status ]  
    download multiple files: start [absoulte_path_1] [absoulte_path_2] ...  
    start -e m-n/len absoulte_path${%d}: expand filename suffix, download same filename with serial number m to n. len is num string length, less than len will filling zero at front  
    eg: start -e 1-15/2 xxx.rar.part${%d} means download xxx.rar.part01, part02, ..., part15  
    start -e 1,3,5 absoulte_path{%d}: expand filename suffix, download same filename with suffix 1,3,5  
    eg: start -e 1,3,5 xxx.rar.part${%d} means download xxx.rar.part1, part3, part5  
    list [ -d | -r ] downloading | removed tasks  
    remove/restore [-all -e n-m | 1,2,3] (task1 task2 ...)  
