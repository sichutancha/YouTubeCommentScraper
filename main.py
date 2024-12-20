import argparse
import time
import json
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from webdriver_manager.firefox import GeckoDriverManager
from bs4 import BeautifulSoup
from tqdm import tqdm
from jinja2 import Environment, FileSystemLoader
import re
import platform
import os

class YouTubeCommentScraper:
    def __init__(self):
        self.setup_driver()
        self.max_videos = None  # 移除视频数量限制
        
    def setup_driver(self):
        """设置Firefox浏览器驱动"""
        firefox_options = Options()
        firefox_options.add_argument('--headless')  # 无头模式
        firefox_options.set_preference("intl.accept_languages", "zh-CN, zh")
        
        try:
            # 使用 GeckoDriverManager 自动下载和管理 Firefox 驱动
            driver_path = GeckoDriverManager().install()
            print(f"Firefox Driver 路径: {driver_path}")
            
            service = Service(driver_path)
            self.driver = webdriver.Firefox(service=service, options=firefox_options)
            
        except Exception as e:
            print(f"设置 Firefox 驱动时出错: {str(e)}")
            print("请确保已安装 Firefox 浏览器")
            raise
            
        self.wait = WebDriverWait(self.driver, 10)
        
    def get_video_list(self):
        """获取频道视频列表"""
        videos = []
        seen_urls = set()  # 用于存储已见过的URL
        
        try:
            # 等待视频列表容器加载
            print("等待页面加载...")
            container_selector = "ytd-rich-grid-renderer"
            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.TAG_NAME, container_selector))
                )
            except TimeoutException:
                print("无法找到视频列表容器，可能是页面结构已更改或加载失败")
                return videos
                
            time.sleep(3)  # 额外等待以确保页面完全加载
            
            print("开始加载视频列表...")
            # 滚动加载更多视频，直到没有新内容
            last_video_count = 0
            no_new_videos_count = 0
            max_attempts = 50  # 增加最大尝试次数
            
            with tqdm(desc="加载视频列表") as pbar:
                while no_new_videos_count < 3 and max_attempts > 0:  # 连续3次没有新视频才停止
                    # 滚动到底部
                    self.driver.execute_script("""
                        window.scrollTo({
                            top: document.documentElement.scrollHeight,
                            behavior: 'smooth'
                        });
                    """)
                    time.sleep(2)
                    
                    try:
                        # 获取当前可见的视频元素数量
                        video_elements = self.driver.find_elements(By.CSS_SELECTOR, "ytd-rich-item-renderer")
                        current_video_count = len(video_elements)
                        
                        if current_video_count > last_video_count:
                            # 更新进度条
                            pbar.update(current_video_count - last_video_count)
                            last_video_count = current_video_count
                            no_new_videos_count = 0
                        else:
                            no_new_videos_count += 1
                        
                        max_attempts -= 1
                        
                    except Exception as e:
                        print(f"滚动加载时出错: {str(e)}")
                        break
            
            print(f"\n已加载 {last_video_count} 个视频元素")
            
            # 获取所有视频信息
            video_elements = self.driver.find_elements(By.CSS_SELECTOR, "ytd-rich-item-renderer")
            
            for video in tqdm(video_elements, desc="处理视频信息"):
                try:
                    # 获取视频链接和缩略图
                    video_data = self.driver.execute_script("""
                        function getVideoData(element) {
                            const thumbnail = element.querySelector('#thumbnail img');
                            const link = element.querySelector('a#video-title-link');
                            const title = link ? link.getAttribute('title') : '';
                            
                            if (!thumbnail || !link) return null;
                            
                            const thumbnailUrl = thumbnail.src || 
                                               thumbnail.dataset.src || 
                                               (thumbnail.srcset ? thumbnail.srcset.split(' ')[0] : null);
                            
                            return {
                                url: link.href,
                                title: title,
                                thumbnail: thumbnailUrl
                            };
                        }
                        return getVideoData(arguments[0]);
                    """, video)
                    
                    if video_data and video_data['url'] and video_data['thumbnail']:
                        # 检查URL是否已经存在
                        video_url = video_data['url']
                        if video_url not in seen_urls:
                            seen_urls.add(video_url)
                            videos.append(video_data)
                except Exception as e:
                    print(f"处理视频元素时出错: {str(e)}")
                    continue
            
            print(f"\n找到 {len(videos)} 个唯一视频")
            return videos
            
        except Exception as e:
            print(f"获取视频列表时出错: {str(e)}")
            return videos

    def process_video(self, video_url):
        """处理单个视频"""
        try:
            self.driver.get(video_url)
            time.sleep(5)  # 等待页面加载
            
            # 获取视频标题
            title = self.driver.find_element(By.CSS_SELECTOR, "h1.ytd-video-primary-info-renderer").text.strip()
            print(f"\n正在处理视频: {title}")
            
            # 确保评论区加载
            self.load_comments_section()
            
            # 获取评论
            comments = self.get_comments()
            return {
                'url': video_url,
                'title': title,
                'comments': comments
            }
            
        except Exception as e:
            print(f"处理视频时出错: {str(e)}")
            return None

    def load_comments_section(self):
        """确保评论区完全加载"""
        try:
            # 等待评论区出现
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "ytd-comments"))
            )
            
            # 滚动到评论区
            comments_section = self.driver.find_element(By.TAG_NAME, "ytd-comments")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", comments_section)
            time.sleep(3)
            
            # 等待第一条评论加载
            WebDriverWait(self.driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "ytd-comment-thread-renderer"))
            )
            
            return True
        except Exception as e:
            print(f"加载评论区时出错: {str(e)}")
            return False

    def get_comments(self):
        """获取视频评论"""
        comments = []
        
        try:
            # 等待评论区加载
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "ytd-comments"))
            )
            time.sleep(3)
            
            # 滚动到评论区
            comments_section = self.driver.find_element(By.TAG_NAME, "ytd-comments")
            self.driver.execute_script("arguments[0].scrollIntoView(true);", comments_section)
            time.sleep(2)
            
            # 分批加载评论
            last_comment_count = 0
            no_new_comments_count = 0
            max_attempts = 30
            
            for attempt in range(max_attempts):
                # 滚动到底部
                self.driver.execute_script("""
                    window.scrollTo(0, document.documentElement.scrollHeight);
                    
                    // 尝试点击所有的"显示回复"按钮
                    document.querySelectorAll('ytd-button-renderer#more-replies:not([hidden])').forEach(button => {
                        if (button.offsetParent !== null) {
                            button.click();
                        }
                    });
                """)
                time.sleep(2)
                
                # 获取当前评论数
                current_comments = self.driver.execute_script("""
                    return document.querySelectorAll('ytd-comment-thread-renderer').length;
                """)
                
                print(f"\r已加载 {current_comments} 条评论线程", end="")
                
                # 检查是否有新评论加载
                if current_comments == last_comment_count:
                    no_new_comments_count += 1
                    if no_new_comments_count >= 3:  # 连续3次没有新评论，认为加载完成
                        break
                else:
                    no_new_comments_count = 0
                    last_comment_count = current_comments
                
                # 每5次滚动尝试获取一次评论
                if attempt % 5 == 0:
                    # 获取评论数据
                    new_comments = self.driver.execute_script("""
                        const comments = [];
                        const threads = document.querySelectorAll('ytd-comment-thread-renderer');
                        
                        threads.forEach(thread => {
                            try {
                                // 获取主评论
                                const mainComment = thread.querySelector('#comment');
                                if (!mainComment) return;
                                
                                const author = mainComment.querySelector('#author-text').textContent.trim();
                                const content = mainComment.querySelector('#content-text').textContent.trim();
                                const likes = mainComment.querySelector('#vote-count-middle').textContent.trim() || '0';
                                const time = mainComment.querySelector('#published-time-text').textContent.trim();
                                
                                comments.push({
                                    author: author,
                                    text: content,
                                    like_count: likes,
                                    published_at: time,
                                    is_reply: false
                                });
                                
                                // 获取回复
                                const replies = thread.querySelectorAll('ytd-comment-renderer.ytd-comment-replies-renderer');
                                replies.forEach(reply => {
                                    try {
                                        const replyAuthor = reply.querySelector('#author-text').textContent.trim();
                                        const replyContent = reply.querySelector('#content-text').textContent.trim();
                                        const replyLikes = reply.querySelector('#vote-count-middle').textContent.trim() || '0';
                                        const replyTime = reply.querySelector('#published-time-text').textContent.trim();
                                        
                                        comments.push({
                                            author: replyAuthor,
                                            text: replyContent,
                                            like_count: replyLikes,
                                            published_at: replyTime,
                                            is_reply: true
                                        });
                                    } catch (e) {
                                        // 忽略单个回复的错误
                                    }
                                });
                            } catch (e) {
                                // 忽略单个评论线程的错误
                            }
                        });
                        return comments;
                    """)
                    
                    if new_comments:
                        comments = new_comments  # 更新评论列表
            
            print(f"\n成功获取 {len(comments)} 条评论（包括回复）")
            return comments
            
        except Exception as e:
            print(f"\n获取评论时出错: {str(e)}")
            return comments

    def generate_report(self, videos):
        """生成HTML报告"""
        try:
            # 加载模板
            template_loader = FileSystemLoader(searchpath="./templates")
            template_env = Environment(loader=template_loader)
            template = template_env.get_template("report_template.html")
            
            # 渲染模板
            html_content = template.render(videos=videos)
            
            # 保存报告
            with open('report.html', 'w', encoding='utf-8') as f:
                f.write(html_content)
            
            print("\n报告已生成: report.html")
            
        except Exception as e:
            print(f"生成报告时出错: {str(e)}")

    def close(self):
        """关闭浏览器"""
        self.driver.quit()

def main():
    parser = argparse.ArgumentParser(description='YouTube评论爬虫')
    parser.add_argument('url', help='YouTube频道或视频URL')
    args = parser.parse_args()
    
    scraper = YouTubeCommentScraper()
    
    try:
        # 处理输入的URL
        channel_url = args.url
        if not channel_url.endswith('/videos'):
            channel_url = channel_url.rstrip('/') + '/videos'
        
        print(f"正在访问: {channel_url}")
        scraper.driver.get(channel_url)
        time.sleep(5)  # 给页面足够的加载时间
        
        videos = scraper.get_video_list()
        if not videos:
            print("未找到任何视频")
            return
            
        # 处理每个视频的评论
        all_video_data = []
        for video in videos:
            video_data = scraper.process_video(video['url'])
            if video_data:
                all_video_data.append(video_data)
        
        # 生成报告
        scraper.generate_report(all_video_data)
        
    except Exception as e:
        print(f"发生错误: {str(e)}")
    finally:
        scraper.driver.quit()

if __name__ == "__main__":
    main()
