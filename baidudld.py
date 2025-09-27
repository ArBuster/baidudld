#! /usr/bin/python
# coding=utf-8

import sys, os
import subprocess
import re
import signal
import logging
import json
from io import TextIOWrapper
from time import sleep
import shutil
import hashlib

logger = logging.getLogger("baidudld")

Global_Options = {
    "daemon": False,
    "verbose": False
}

MAX_SLEEP_TIME=5
SAVE_DIR=""
RECORD_PATH=os.path.join(os.environ["HOME"], ".config/BaiduPCS-Go")


def print_usage():
    name=os.path.basename(__file__).split('.')[0]
    print("unknown parameters: %s" % " ".join(sys.argv[1:]))
    print("\nUsage: %s [ option ] command" % name)
    print("\n    option:")
    print("\n    --daemon: run as daemon")
    print("\n    --verbose: write baidupcs output to file")
    print("\n    command: [ start | stop | resume | list | remove | restore | clean ]")
    print("\n    download multiple files: start [absoulte_path_1] [absoulte_path_2] ...")
    print("\n    start -e m-n absoulte_path(%d): expand filename suffix, download same filename with serial number m to n")
    print("\n    eg: start -e 1-3 xxx.rar.part%d means download xxx.rar.part1, part2, part3")
    print("\n    start -e 1,3,5 absoulte_path(%d): expand filename suffix, download same filename with suffix 1,3,5")
    print("\n    eg: start -e 1,3,5 xxx.rar.part%d means download xxx.rar.part1, part3, part5")
    print("\n    list [ -d | -r ] downloading | removed tasks")
    print("\n    remove/restore [-all -e n-m | 1,2,3] (task1 task2 ...)\n")


def test_run() -> tuple:
    cmd = ("pgrep", "-f", "baidupcs d")
    ps_ret = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf8")

    return tuple(int(pid) for pid in ps_ret.stdout.split('\n') if pid.isdigit())


# 获取baidupcs配置文件中的下载保存目录
def get_savedir():
    global SAVE_DIR
    SAVE_DIR=os.path.dirname(RECORD_PATH)
    reg = R'"savedir"\s*:\s*"([^"]+)"'
    with open(os.path.join(RECORD_PATH, "pcs_config.json"), "r+") as f:
        conf = f.read()
        regex = re.search(reg, conf)
        if regex:
            SAVE_DIR = regex.group(1)
            while SAVE_DIR[-1] == '/' and len(SAVE_DIR) > 1:
                SAVE_DIR = SAVE_DIR[:-1]
            if SAVE_DIR != regex.group(1):
                f.seek(0)
                f.truncate(0)
                f.write(conf.replace(regex.group(1), SAVE_DIR))
                f.flush()


# 退出下载进程，成功返回True
def stop_task(log_level=logging.INFO) -> bool:
    logger.setLevel(log_level)
    logger.info("stopping baidupcs ...")

    pids, ret = test_run(), True
    if pids:
        for pid in pids:
            os.kill(pid, signal.SIGINT)

        success = False
        for i in range(0, MAX_SLEEP_TIME):
            sleep(1)
            if not test_run():
                success = True
                break
        else:
            for pid in test_run():
                os.kill(pid, signal.SIGKILL)

        if success:
            logger.info("baidupcs stop success.")
        else:
            logger.error("baidupcs stop failed. use SIGKILL(kill -9) retry ...")
            for i in range(0, MAX_SLEEP_TIME):
                sleep(1)
                if not test_run():
                    logger.error("baidupcs SIGKILL(kill -9) success.")
                    break
            else:
                ret = False
                logger.error("baidupcs SIGKILL(kill -9) failed.")

    else:
        logger.info("baidupcs not running.")

    return ret


def start_task(argv:list[str]) -> bool:
    if argv[0] != "-e":
        return download_multiple_files(argv)
    else:
        return download_multiple_files(expand_suffix(argv[1:]))


# 展开同名文件数字后缀
def expand_suffix(argv:list[str]) -> list[str]:
    files_expand = list()
    if len(argv) == 2 and argv[1].count("%d") == 1:
        suffix_1 = R"^(\d+)-(\d+)$"
        suffix_2 = R"^(\d+,)+\d$"

        regex = re.match(suffix_1, argv[0]) or re.match(suffix_2, argv[0])
        if regex:
            if len(regex.groups()) == 2 and int(regex.group(1)) < int(regex.group(2)):
                for i in range(int(regex.group(1)), int(regex.group(2))+1):
                    files_expand.append(argv[1].replace("%d", str(i)))
            else:
                files_expand=[argv[1].replace("%d", i) for i in argv[0].split(',')]

    if not files_expand:
        print_usage()

    return files_expand


def record_path(category:str) -> str:
    match category:
        case "downloading":
            f_path = os.path.join(RECORD_PATH, "task_record")
        case "removed":
            f_path = os.path.join(RECORD_PATH, "task_removed")
        case _:
            logger.warning("task category %s unknown." % category)
            return ""
    return f_path


# 更新任务记录文件
def update_task_record(tasks:dict[str,dict], category:str="downloading"):
    f_path = record_path(category)
    if not f_path:
        return

    with open(f_path, "w") as f:
        json.dump(tasks, f, ensure_ascii=False, indent=2, sort_keys=True)


# 读取任务记录，正在下载和已删除未完成的任务记录
def load_task_record(category:str="downloading") -> dict[str,dict]:
    f_path = record_path(category)
    if not f_path:
        return dict()

    if not os.path.isfile(f_path):
        with open(f_path, "w") as f:
            json.dump(dict(), f)

    with open(f_path, "r") as f:
        tasks = json.load(f)

    return tasks


# 开始下载任务，更新任务列表
def download_multiple_files(argv:list[str], log_level=logging.INFO) -> bool:
    ret = True
    tasks = load_task_record()
    for a in argv:
        while a[-1] == '/' and len(a) > 1: a = a[:-1]
        if a not in tasks:
            tasks[a] = dict()

    if not stop_task(logging.WARN) or not tasks:
        logger.info("no task to start.")
        return ret

    logger.setLevel(log_level)
    logger.info("tasks starting ...")

    tasks = get_downloading_save_path(tasks)
    tasks = check_task_complete(tasks)
    if tasks:
        logger.info("These tasks will be start:")
        for t in tasks:
            logger.info(t)
        logger.info("")
    else:
        logger.info("All tasks done. there is no task to be start.")
        return ret

    dt = list(tasks.keys())
    dt.sort()
    cmd = ["baidupcs", "d"] + dt
    if Global_Options["verbose"]:
        output_f = open(os.path.join(SAVE_DIR, "baidupcs_output.txt"), "w")
        proc = subprocess.Popen(cmd, stdout=output_f, stderr=subprocess.STDOUT, encoding="utf8")
    else:
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    success = False
    for i in range(0, MAX_SLEEP_TIME):
        sleep(1)
        if test_run():
            success = True
            break

    if success:
        update_task_record(tasks)
        logger.info("tasks start success.")
    else:
        ret = False
        if Global_Options["verbose"]:
            logger.critical("tasks start failed. subprocess.run stdout:\n")
            with open(os.path.join(SAVE_DIR, "baidupcs_output.txt"), "r") as f:
                logger.critical(f.read())
        else:
            print("tasks start failed. use --verbose to get more information\n")

    return ret


# 记录任务下载保存的位置
def get_downloading_save_path(tasks:dict[str,dict]) -> dict[str,dict]:
    temp_save = os.path.join(SAVE_DIR, "baidudld_temp")
    def create_temp_dir(temp_save:str):
        if not os.path.exists(temp_save):
            os.mkdir(temp_save)
        with open(os.path.join(RECORD_PATH, "pcs_config.json"), "r+") as f:
            conf = f.read()
            if temp_save not in conf:
                conf = conf.replace(SAVE_DIR, temp_save)
                f.seek(0)
                f.truncate(0)
                f.write(conf)
                f.flush()

    def delete_temp_dir(temp_save: str):
        if os.path.exists(temp_save):
            with open(os.path.join(RECORD_PATH, "pcs_config.json"), "r+") as f:
                conf = f.read()
                conf = conf.replace(temp_save, SAVE_DIR)
                f.seek(0)
                f.truncate(0)
                f.write(conf)
                f.flush()
            shutil.rmtree(temp_save)


    create_temp_dir(temp_save)
    del_tasks = list()
    for task, value in tasks.items():
        if value: continue

        re_path = re.compile(R"将会下载到路径:\s*%s/([^/]+)/" % re.escape(temp_save))
        re_type = re.compile(R"类型\s+(文件|目录)\s+(文件|目录)路径\s+%s\s+(文件|目录)名称"
                             % re.escape(task))

        baidudld_temp = os.path.join(RECORD_PATH, "baidudld.temp")
        with open(baidudld_temp, "w") as f_temp:
            cmd = ["baidupcs", "d", task]
            proc = subprocess.Popen(
                cmd, stdout=f_temp, stderr=subprocess.STDOUT, encoding="utf8")

            with open(baidudld_temp, "r") as f:
                for i in range(0, MAX_SLEEP_TIME):
                    sleep(1)
                    proc_output = f.read()
                    reg_path, reg_type = re_path.search(proc_output), re_type.search(proc_output)
                    if reg_path and reg_type:
                        value["type"] = reg_type.group(1)
                        value["path"] = os.path.join(SAVE_DIR, reg_path.group(1), os.path.basename(task))
                        files_info = get_files_info(proc_output, value["type"])
                        if value["type"] == "目录":
                            value["sub_files"] = files_info
                            for sub_task, sub_v in value["sub_files"].items():
                                sub_v["path"] = value["path"] + sub_task.replace(task, "")
                        else:
                            value.update(files_info)
                        break

            proc.send_signal(signal.SIGINT)
            for i in range(0, MAX_SLEEP_TIME):
                sleep(1)
                if proc.poll() is not None: break
            else:
                proc.kill()

        if not value: del_tasks.append(task)

    for key in del_tasks: del tasks[key]

    delete_temp_dir(temp_save)
    return tasks


# 记录下载文件的大小Byte，md5校验和，如果是目录，递归记录目录中下载的文件
def get_files_info(proc_output:str, download_type:str) -> dict[str, dict]:
    ret = dict()

    if download_type == "目录":
        all_tasks = re.findall(R"加入下载队列:\s*(.+)", proc_output)

        # 去掉目录递归的任务
        n = len(all_tasks) - 1
        for i in range(n, -1, -1):
            task = all_tasks.pop(i)
            for t in all_tasks:
                if task in t:
                    break
            else:
                all_tasks.insert(i, task)

        if all_tasks:
            ret = get_downloading_save_path({t: {} for t in all_tasks})
        return ret


    reg_info = R"文件名称\s+(.+)\s+文件大小\s+(\d+).*\s+md5[^0-9a-z]*([0-9a-z]{32})"
    file_info = re.findall(reg_info, proc_output)
    for info in file_info:
        ret = {
            "filename": info[0].strip(),
            "size": int(info[1]),
            "md5": info[2]
        }

    return ret


# Byte单位转换，转换成KB/MB/GB，要求数值大于1，用于打印时直观显示文件大小
def convert_file_size(size:int) -> str:
    unit = 0
    for i in range(0, 4):
        if size / pow(1024, i) > 1:
            unit = i
        else:
            size /= pow(1024, i - 1)
            break
    else:
        size /= pow(1024, unit)

    ret = str(round(size, 2)) + " "
    unit_str = "B"
    match unit:
        case 1: unit_str = "KB"
        case 2: unit_str = "MB"
        case 3: unit_str = "GB"
        case _: pass

    return ret + unit_str


# 打印任务进度
def list_tasks(category:str="downloading"):
    tasks = load_task_record(category)
    if not tasks:
        print("There is no task %s." % category)
        return

    print("These tasks are %s:\n" % category)
    print("files      download   total    percent\n")

    total_files, total_download, total_size = 0, 0, 0
    for task, info in tasks.items():
        print("task: " + task)
        downloaded_size = 0
        if info["type"] == "文件":
            full_size = info["size"]
            total_files += 1
            total_size += full_size
            if os.path.exists(info["path"]):
                downloaded_size = os.path.getsize(info["path"])
                total_download += downloaded_size

            percent = downloaded_size * 100 / full_size
            downloaded_size = convert_file_size(downloaded_size)
            full_size = convert_file_size(full_size)
            print("1 file     %s | %s  %s" % (downloaded_size, full_size, "{:.2f}%".format(percent)))
        else:
            sub_files = len(info["sub_files"])
            total_files += sub_files
            full_size = 0
            for sub_info in info["sub_files"].values():
                full_size += sub_info["size"]
                if os.path.exists(sub_info["path"]):
                    downloaded_size += os.path.getsize(sub_info["path"])

            total_download += downloaded_size
            total_size += full_size
            percent = downloaded_size * 100 / full_size
            downloaded_size = convert_file_size(downloaded_size)
            full_size = convert_file_size(full_size)
            print("%d files    %s | %s  %s" % (sub_files, downloaded_size, full_size, "{:.2f}%".format(percent)))

    print("\nTotal:")
    total_precent = total_download * 100 / total_size
    total_download = convert_file_size(total_download)
    total_size = convert_file_size(total_size)
    print("%d files    %s | %s  %s" % (total_files, total_download, total_size, "{:.2f}%".format(total_precent)))


# 移除指定的未完成的下载任务，记录进task_removed，更新task_record
def remove_task(argv:list[str]):
    tasks, remove_new = load_task_record(), dict()

    if argv[0] == "-e":
        argv = expand_suffix(argv[1:])

    if argv[0] == "-all":
        remove_new |= tasks
        print("\n%d tasks are removed." % len(tasks))
        tasks.clear()
    else:
        for a in argv:
            if a in tasks:
                remove_new |= {a: tasks.pop(a)}
                print("task %s is removed." % a)
            else:
                print("%s is not in the task." % a)

    if not remove_new:
        return

    update_task_record(tasks)
    remove_new |= load_task_record("removed")
    update_task_record(remove_new, "removed")

    print("\nuse resume to take effect.")


# 恢复指定的被移除的下载任务，记录进task_record，更新task_removed
def restore_task(argv:list[str]):
    removed, tasks_new = load_task_record("removed"), dict()

    if argv[0] == "-e":
        argv = expand_suffix(argv[1:])

    if argv[0] == "-all":
        tasks_new |= removed
        print("\n%d tasks are restored." % len(removed))
        removed.clear()
    else:
        for a in argv:
            if a in removed:
                tasks_new |= {a: removed.pop(a)}
                print("task %s is restored." % a)
            else:
                print("%s is not in the task." % a)

    if not tasks_new:
        return

    update_task_record(removed, "removed")
    tasks_new |= load_task_record()
    update_task_record(tasks_new)

    print("\nuse resume to take effect.")


# 检查任务进度，下载完成的文件移除任务记录
# 判断完成使用非严格检查：
# 只要没有*.BaiduPCS-Go-downloading文件
# 同时下载文件大小等于服务器告知的大小
# 对文件进行md5下载校验，输出结果到下载目录
def check_task_complete(tasks:dict[str, dict]) -> dict[str, dict]:
    def test_task_complete(path:str, size:int) -> bool:
        return (os.path.exists(path) and
                not os.path.exists(path + R".BaiduPCS-Go-downloading")
                and os.path.getsize(path) == size)

    complete_tasks = dict()
    for task, info in tasks.items():
        if info["type"] == "文件":
            if test_task_complete(info["path"], info["size"]):
                complete_tasks |= {task: info}
        else:
            for sub_info in info["sub_files"].values():
                if not test_task_complete(sub_info["path"], sub_info["size"]):
                    break
            else:
                complete_tasks |= {task: info}

    if complete_tasks:
        complete_tasks = file_md5_hash(complete_tasks)
        print_hash_verify(complete_tasks)
        for ct in complete_tasks:
            del tasks[ct]
        update_task_record(tasks)

    return tasks


# 计算比较文件md5
def file_md5_hash(tasks:dict[str, dict]) -> dict[str, dict]:
    for info in tasks.values():
        md5_hash = hashlib.md5()
        if info["type"] == "文件":
            with open(info["path"], "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    md5_hash.update(chunk)
            info["hash_verify"] = md5_hash.hexdigest().lower()
        else:
            info = file_md5_hash(info["sub_files"])

    return tasks


# 打印md5校验检查结果
def print_hash_verify(tasks: dict[str, dict]):
    for key, info in tasks.items():
        if info["type"] == "文件":
            hash_file = os.path.join(os.path.dirname(info["path"]),
                                     os.path.basename(key) + "_hash_verify")
            with open(hash_file, "w") as f:
                write_hash_file(f, info)
        else:
            hash_file = os.path.join(os.path.dirname(info["path"]),
                                     os.path.basename(key), "hash_verify")
            with open(hash_file, "w") as f:
                for sub_info in info["sub_files"].values():
                    write_hash_file(f, sub_info)


def write_hash_file(f:TextIOWrapper, file_info:dict):
    f.write(file_info["path"] + os.linesep)
    if file_info["hash_verify"] == file_info["md5"]:
        f.write("OK" + os.linesep)
    else:
        f.write(file_info["hash_verify"] + "    ==>  server: " + file_info["md5"] + os.linesep)
    f.write(os.linesep)


def resume_task(log_level=logging.INFO):
    logger.setLevel(log_level)
    logger.info("restoring tasks ...\n")
    download_multiple_files([], log_level)


# 根据task_removed记录，清理未完成被移除的下载任务文件
def clean_tasks():
    resume_task(logging.WARN)

    removed = load_task_record("removed")
    print("These tasks and files / directories will be delete:\n")
    for task, info in removed.items():
        path = info["path"]
        info["clean"] = list()
        if info["type"] == "文件":
            path_downloading = path + R".BaiduPCS-Go-downloading"
            if os.path.exists(path_downloading):
                info["clean"].append(path_downloading)
                if os.path.exists(path):
                    info["clean"].append(path)
        elif os.path.exists(path):
            dir_clean = True
            for sub_info in info["sub_files"].values():
                if os.path.exists(sub_info["path"] + R".BaiduPCS-Go-downloading"):
                    dir_clean = True
                    break
                if os.path.exists(sub_info["path"]):
                    dir_clean = False

            if dir_clean:
                info["clean"].append(path)

        print("task: %s :\n%s\n" % (task, [os.path.basename(p) for p in info["clean"]]))

    while True:
        print("input Y to confirm, N to cancel:")
        ch = sys.stdin.read(1)
        if ch.upper() == 'Y':
            break
        elif ch.upper() == 'N':
            print("user canceled.")
            return
        else:
            while ch != '\n': ch = sys.stdin.read(1)

    for info in removed.values():
        if info["clean"]:
            if info["type"] == "文件":
                for path in info["clean"]:
                    os.remove(path)
            else:
                shutil.rmtree(info["clean"][0])

    removed.clear()
    update_task_record(removed, "removed")
    print("tasks cleaned.")


# 以守护进程方式运行
def run_as_daemon():
    def handler(signum, frame):
        stop_task(logging.WARN)
        print("baidudld daemon stoped.")
        sys.exit(0)

    print("baidudld running as daemon.")
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)
    while True:
        sleep(15)
        if load_task_record() and not test_run():
            resume_task(logging.WARN)


# 处理输入选项参数
def read_global_options(argv: list[str]) -> list[str]:
    global Global_Options

    if "--daemon" in argv:
        Global_Options["daemon"] = True
        argv.remove("--daemon")
    if "--verbose" in argv:
        Global_Options["verbose"] = True
        argv.remove("--verbose")

    return argv


if __name__ == "__main__":
    logging.basicConfig(format="%(message)s", level=logging.INFO)

    argv = read_global_options(sys.argv)
    get_savedir()

    if len(argv) > 1:
        match argv[1]:
            case "start":
                if len(argv) >= 3:
                    start_task(argv[2:])
                    if Global_Options["daemon"]: run_as_daemon()
                else:
                    print_usage()
            case "stop":
                stop_task()
            case "resume":
                resume_task()
                if Global_Options["daemon"]: run_as_daemon()
            case "list":
                if len(argv) > 2:
                    if argv[2] == "-r":
                        list_tasks("removed")
                    elif argv[2] != "-d":
                        print_usage()
                else:
                    list_tasks()
            case "remove":
                if len(argv) >= 3:
                    remove_task(argv[2:])
                else:
                    print_usage()
            case "restore":
                if len(argv) >= 3:
                    restore_task(argv[2:])
                else:
                    print_usage()
            case "clean":
                clean_tasks()
            case _:
                print_usage()
    else:
        print_usage()
