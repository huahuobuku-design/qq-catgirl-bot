"""Portable Tk control panel. No account/session reuse or bundled QQ runtime."""
import asyncio
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser

from bot import OneBot
from catgirl import CatGirl
from configuration import load_config, save_config, validate_config
from runtime_guard import InstanceLock

ROOT = Path(__file__).parent


class Panel:
    def __init__(self, window):
        self.window = window
        self.config = load_config(ROOT/'config.json')
        self.process = None
        self.busy = False
        self.history = []
        self.events = queue.Queue()
        self.fields = {}
        window.title('QQ猫娘 · API版')
        window.geometry('900x760')
        frame = ttk.Frame(window, padding=20); frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='猫娘的小窝 ฅ^•ﻌ•^ฅ', font=('', 22, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='配置API → 本地试聊 → 登录自己的OneBot客户端 → 开启指定群回复').pack(anchor='w', pady=10)
        form = ttk.LabelFrame(frame, text='连接配置', padding=12); form.pack(fill='x')
        llm = self.config['engine']['llm']
        values = [('onebot_url','QQ WebSocket地址',self.config['onebot_url']),
                  ('access_token','OneBot Token',self.config['access_token']),
                  ('groups','允许回复的群号（逗号分隔）',','.join(map(str,self.config['groups']['whitelist']))),
                  ('base_url','模型API地址',llm['base_url']), ('model','模型ID',llm['model']),
                  ('api_key','API Key（可改用环境变量）',llm['api_key'])]
        for row,(key,label,value) in enumerate(values):
            ttk.Label(form,text=label).grid(row=row,column=0,sticky='w',padx=8,pady=4)
            variable=tk.StringVar(value=value); self.fields[key]=variable
            ttk.Entry(form,textvariable=variable,show='*' if key in ('api_key','access_token') else '').grid(row=row,column=1,sticky='ew')
        form.columnconfigure(1,weight=1)
        self.all_messages=tk.BooleanVar(value=self.config['reply']['trigger']=='all')
        ttk.Checkbutton(frame,text='回复指定群的所有文字（默认仅@或含“猫娘”时回复）',variable=self.all_messages).pack(anchor='w',pady=8)
        row=ttk.Frame(frame);row.pack(fill='x',pady=6)
        for title,command in [('保存配置',self.save),('检查QQ',self.diagnose),('开启群回复',self.start),('停止群回复',self.stop),('导入表情包',self.import_stickers)]:
            ttk.Button(row,text=title,command=command).pack(side='left',padx=(0,8))
        self.status=tk.StringVar(value='未开启群回复 · 本地试聊不向QQ发送消息')
        ttk.Label(frame,textvariable=self.status,wraplength=850).pack(anchor='w',pady=8)
        self.output=tk.Text(frame,wrap='word',state='disabled');self.output.pack(fill='both',expand=True)
        row=ttk.Frame(frame);row.pack(fill='x',pady=10)
        self.input=ttk.Entry(row);self.input.pack(side='left',fill='x',expand=True)
        self.input.bind('<Return>',lambda event:self.chat())
        ttk.Button(row,text='本地试聊',command=self.chat).pack(side='left',padx=8)
        window.protocol('WM_DELETE_WINDOW',self.close);window.after(100,self.poll)

    def save(self):
        try:
            values={key:value.get().strip() for key,value in self.fields.items()}
            self.config['onebot_url']=values['onebot_url'];self.config['access_token']=values['access_token']
            self.config['groups']['whitelist']=[int(g.strip()) for g in values['groups'].replace('，',',').split(',') if g.strip()]
            self.config['reply']['trigger']='all' if self.all_messages.get() else 'mention_or_keyword'
            self.config['engine']['llm'].update({key:values[key] for key in ('base_url','model','api_key')})
            save_config(ROOT/'config.json',self.config)
            self.status.set('已保存 · 已运行的群回复需停止后重启以应用配置')
            return True
        except (ValueError,OSError) as error:
            messagebox.showerror('配置未保存',str(error));return False

    def write(self,text):
        self.output.configure(state='normal');self.output.insert('end',str(text)+'\n')
        self.output.see('end');self.output.configure(state='disabled')

    def diagnose(self):
        if not self.save():return
        config=json.loads(json.dumps(self.config))
        def work():
            async def probe():
                client=OneBot(config['onebot_url'],config['access_token']);pump=None
                try:
                    await asyncio.wait_for(client.connect(),5);pump=asyncio.create_task(client.pump())
                    result=await client.call('get_login_info',{},timeout=5)
                    logged_in=result.get('retcode')==0 and (result.get('data') or {}).get('user_id')
                    self.events.put(('status','QQ已接通并登录' if logged_in else '接口已连接，QQ登录尚未确认'))
                except Exception:
                    self.events.put(('status','QQ未接通，请检查登录、正向WebSocket、端口及Token'))
                finally:
                    if pump:pump.cancel()
                    await client.close()
            asyncio.run(probe())
        threading.Thread(target=work,daemon=True).start()

    def start(self):
        if self.process and self.process.poll() is None:return
        if not self.save():return
        try:validate_config(self.config)
        except ValueError as error:messagebox.showerror('尚不能启动',str(error));return
        self.process=subprocess.Popen([sys.executable,'-u',str(ROOT/'bot.py')],cwd=ROOT,
            env=dict(os.environ,PYTHONIOENCODING='utf-8'),stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        process=self.process
        def read():
            for line in process.stdout:self.events.put(('log',line.rstrip()))
            self.events.put(('status',f'群回复已退出，退出码：{process.wait()}'))
        threading.Thread(target=read,daemon=True).start()
        self.status.set('群回复启动中，请查看连接日志')

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait()
        self.status.set('群回复已停止')

    def chat(self):
        if self.busy or not self.save():return
        text=self.input.get().strip()
        if not text:return
        try:validate_config(self.config,require_groups=False)
        except ValueError as error:messagebox.showerror('API未配置',str(error));return
        self.input.delete(0,'end');self.write('你：'+text);self.history.append({'user':'主人','text':text})
        self.history=self.history[-20:];history=list(self.history);config=json.loads(json.dumps(self.config['engine']))
        self.busy=True
        def work():
            try:
                cat=CatGirl(config);reply=asyncio.run(cat.reply(history,history[-1:]))
                sticker=cat.stickers.get(cat.reply_stickers.get('local'))
                if sticker:self.events.put(('log','本地选图：'+sticker['title']+'（未发送QQ）'))
                self.events.put(('chat',reply))
            except Exception as error:self.events.put(('error',str(error)))
        threading.Thread(target=work,daemon=True).start()

    def import_stickers(self):
        process=subprocess.run([sys.executable,str(ROOT/'import_stickers.py')],cwd=ROOT,capture_output=True,
                               text=True,encoding='utf-8',errors='replace',creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.write(process.stdout.strip() or process.stderr.strip())
        webbrowser.open((ROOT/'stickers').as_uri())

    def poll(self):
        try:
            while True:
                kind,text=self.events.get_nowait()
                if kind=='status':self.status.set(text)
                elif kind=='chat':
                    self.write('猫娘：'+text);self.history.append({'user':'猫娘','text':text});self.busy=False
                elif kind=='error':self.write('调用失败：'+text);self.busy=False
                else:self.write(text)
        except queue.Empty:pass
        self.window.after(100,self.poll)

    def close(self):self.stop();self.window.destroy()


if __name__=='__main__':
    guard=InstanceLock(ROOT/'data/panel.lock')
    if not guard.acquire():raise SystemExit('控制台已打开，请使用现有窗口')
    try:
        root=tk.Tk();Panel(root);root.mainloop()
    finally:guard.close()
