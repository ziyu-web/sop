import xml.etree.ElementTree as ET
import re
from datetime import timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from hikiot.utils.log_manager import global_logger

# 标准命名空间常量
HIKVISION_NAMESPACE = "http://www.hikvision.com/ver20/XMLSchema"
STD_CGI_NAMESPACE = "http://www.std-cgi.com/ver20/XMLSchema"

@dataclass
class XmlParseResult:
    """XML解析结果数据类"""
    success: bool
    data: Any = None
    error: str = ""

class XmlProcessor:
    """XML处理模块 - 通用XML处理核心（支持标准命名空间）"""
    
    @staticmethod
    def split_combined_xmls(xml_content: str) -> List[str]:
        """
        将包含多个XML的内容分割成单独的XML字符串列表
        
        Args:
            xml_content: 可能包含多个XML的字符串
        
        Returns:
            单独XML字符串的列表
        """
        if not xml_content or not isinstance(xml_content, str):
            global_logger.error("输入内容为空或不是字符串")
            return []
        
        # 使用正则表达式匹配XML开始和结束标签
        xml_declaration_pattern = r'<\?xml[^>]*\?>'
        start_tag_pattern = r'<[^?!][^>]*>'
        end_tag_pattern = r'</[^>]+>'
        
        # 查找所有可能的XML开始位置
        xml_parts = []
        
        try:
            # 处理有XML声明的情况
            xml_declarations = list(re.finditer(xml_declaration_pattern, xml_content))
            
            if xml_declarations:
                # 有XML声明的情况
                for i, decl_match in enumerate(xml_declarations):
                    start_pos = decl_match.start()
                    # 找下一个XML声明的开始位置或文件结束位置作为当前XML的结束位置
                    next_decl_pos = xml_declarations[i+1].start() if i+1 < len(xml_declarations) else len(xml_content)
                    
                    # 在当前范围内查找根元素开始标签
                    current_content = xml_content[start_pos:next_decl_pos]
                    
                    # 查找根元素开始标签
                    start_tag_match = re.search(start_tag_pattern, current_content)
                    if not start_tag_match:
                        global_logger.warning(f"在XML声明后的内容中未找到根元素开始标签: {current_content[:100]}...")
                        continue
                    
                    # 提取根元素名称（可能包含命名空间）
                    start_tag = start_tag_match.group()
                    # 提取标签名，处理可能的命名空间
                    tag_name_match = re.search(r'<([^\s/>]+)', start_tag)
                    if not tag_name_match:
                        global_logger.warning(f"无法从开始标签中提取标签名: {start_tag}")
                        continue
                    
                    tag_name = tag_name_match.group(1)
                    # 构建对应的结束标签模式
                    end_tag_pattern_for_root = f'</{tag_name}>'
                    
                    # 在当前内容中查找结束标签
                    end_tag_pos = current_content.find(end_tag_pattern_for_root)
                    if end_tag_pos == -1:
                        # 如果找不到匹配的结束标签，尝试查找最外层的结束标签
                        end_tags = list(re.finditer(end_tag_pattern, current_content))
                        if end_tags:
                            end_tag_pos = end_tags[-1].end()
                        else:
                            global_logger.warning(f"在XML内容中未找到结束标签: {current_content[:100]}...")
                            continue
                    else:
                        end_tag_pos += len(end_tag_pattern_for_root)
                    
                    # 提取完整的XML部分
                    xml_part = current_content[:end_tag_pos]
                    xml_parts.append(xml_part)
            else:
                # 没有XML声明的情况，尝试直接分割根元素
                current_pos = 0
                while True:
                    # 查找下一个根元素开始标签
                    start_tag_match = re.search(start_tag_pattern, xml_content[current_pos:])
                    if not start_tag_match:
                        break
                    
                    start_pos = current_pos + start_tag_match.start()
                    current_pos = start_pos + len(start_tag_match.group())
                    
                    # 提取标签名
                    start_tag = start_tag_match.group()
                    tag_name_match = re.search(r'<([^\s/>]+)', start_tag)
                    if not tag_name_match:
                        global_logger.warning(f"无法从开始标签中提取标签名: {start_tag}")
                        continue
                    
                    tag_name = tag_name_match.group(1)
                    end_tag_pattern_for_root = f'</{tag_name}>'
                    
                    # 查找对应的结束标签
                    end_tag_pos = xml_content.find(end_tag_pattern_for_root, current_pos)
                    if end_tag_pos == -1:
                        # 如果找不到，尝试查找最外层的结束标签
                        end_tags = list(re.finditer(end_tag_pattern, xml_content[start_pos:]))
                        if end_tags:
                            end_tag_pos = start_pos + end_tags[-1].end()
                        else:
                            global_logger.warning(f"在XML内容中未找到结束标签: {xml_content[start_pos:start_pos+100]}...")
                            break
                    else:
                        end_tag_pos += len(end_tag_pattern_for_root)
                    
                    xml_part = xml_content[start_pos:end_tag_pos]
                    xml_parts.append(xml_part)
                    current_pos = end_tag_pos
        except Exception as e:
            global_logger.error(f"分割XML内容时出错: {str(e)}")
            return []
        
        return xml_parts
    
    @staticmethod
    def parse_xml(xml_content: str) -> XmlParseResult:
        """
        解析单个XML字符串为ElementTree对象
        
        Args:
            xml_content: 单个XML字符串
        
        Returns:
            XmlParseResult对象，包含解析结果
        """
        if not xml_content:
            return XmlParseResult(False, error="XML内容为空")
        
        try:
            root = ET.fromstring(xml_content)
            return XmlParseResult(True, data=root)
        except ET.ParseError as e:
            global_logger.error(f"XML解析错误: {str(e)}")
            # 尝试清理XML内容，移除可能的BOM等字符
            xml_content = xml_content.strip()
            if xml_content.startswith('\ufeff'):
                xml_content = xml_content[1:]
            try:
                root = ET.fromstring(xml_content)
                return XmlParseResult(True, data=root)
            except ET.ParseError as e2:
                global_logger.error(f"清理后XML解析仍失败: {str(e2)}")
                return XmlParseResult(False, error=f"清理后XML解析失败: {str(e2)}")
        except Exception as e:
            global_logger.error(f"解析XML时发生未知错误: {str(e)}")
            return XmlParseResult(False, error=f"解析XML时发生未知错误: {str(e)}")
    
    @staticmethod
    def detect_namespace(xml_root: ET.Element) -> str:
        """
        检测XML根元素的命名空间类型
        
        Args:
            xml_root: XML根元素
            
        Returns:
            命名空间类型: "hikvision", "std_cgi", "unknown" 或 "none"
        """
        if not xml_root:
            return "unknown"
        
        tag = xml_root.tag
        if tag.startswith('{'):
            if 'hikvision' in tag.lower():
                global_logger.info("检测到Hikvision命名空间")
                return "hikvision"
            elif 'std-cgi' in tag.lower():
                global_logger.info("检测到Std-CGI命名空间")
                return "std_cgi"
            else:
                global_logger.error(f"检测到未知命名空间: {tag}")
                return "unknown"
        else:
            global_logger.info("检测到无命名空间XML")
            return "none"
    
    @staticmethod
    def extract_element_text_smart(xml_root: ET.Element, tag_name: str, default_value: str = "") -> str:
        """
        智能提取元素文本，自动检测命名空间
        
        Args:
            xml_root: XML根元素
            tag_name: 标签名
            default_value: 默认值
            
        Returns:
            标签文本内容
        """
        if not xml_root:
            return default_value
        
        # 检测命名空间类型
        namespace_type = XmlProcessor.detect_namespace(xml_root)
        
        # 根据命名空间类型选择相应的命名空间
        namespace = None
        if namespace_type == "hikvision":
            namespace = HIKVISION_NAMESPACE
        elif namespace_type == "std_cgi":
            namespace = STD_CGI_NAMESPACE
        
        # 使用现有方法进行提取
        return XmlProcessor.extract_element_text(xml_root, tag_name, namespace, default_value)
    
    @staticmethod
    def extract_element_text_unified(xml_root: ET.Element, tag_name: str, default_value: str = "") -> str:
        """
        统一的元素文本提取接口，自动处理命名空间
        
        Args:
            xml_root: XML根元素
            tag_name: 标签名
            default_value: 默认值
            
        Returns:
            标签文本内容
        """
        return XmlProcessor.extract_element_text_smart(xml_root, tag_name, default_value)
    
    @staticmethod
    def validate_namespace(xml_root: ET.Element, expected_namespace: Optional[str] = None) -> bool:
        """
        验证XML命名空间（支持标准命名空间）
        
        Args:
            xml_root: XML根元素
            expected_namespace: 期望的命名空间
            
        Returns:
            是否匹配命名空间
        """
        if not xml_root:
            return False
            
        if expected_namespace is not None:
            # 检查根元素是否包含指定命名空间
            if xml_root.tag.startswith('{') and expected_namespace in xml_root.tag:
                return True
            # 检查是否有命名空间前缀
            if expected_namespace in xml_root.tag:
                return True
        return True  # 如果没有指定命名空间要求，则默认通过
    
    @staticmethod
    def extract_element_text(xml_root: ET.Element, tag_name: str, namespace: Optional[str] = None, 
                           default_value: str = "") -> str:
        """
        提取指定标签的文本内容（支持标准命名空间）
        
        Args:
            xml_root: XML根元素
            tag_name: 标签名
            namespace: 命名空间（可选，支持标准命名空间常量）
            default_value: 默认值
            
        Returns:
            标签文本内容
        """
        if not xml_root:
            return default_value
            
        try:
            # 如果没有指定命名空间，使用默认的Hikvision命名空间
            if not namespace:
                namespace = HIKVISION_NAMESPACE
                
            # 构建查找路径
            search_path = f".//{{{namespace}}}{tag_name}"
            
            element = xml_root.find(search_path)
            if element is not None and element.text:
                return element.text.strip()
            return default_value
        except Exception as e:
            global_logger.warning(f"提取元素文本时出错: {str(e)}")
            return default_value
    
    @staticmethod
    def extract_element_attributes(xml_root: ET.Element, tag_name: str, namespace: Optional[str] = None) -> Dict[str, str]:
        """
        提取指定标签的属性（支持标准命名空间）
        
        Args:
            xml_root: XML根元素
            tag_name: 标签名
            namespace: 命名空间（可选）
            
        Returns:
            属性字典
        """
        if not xml_root:
            return {}
            
        try:
            # 如果没有指定命名空间，使用默认的Hikvision命名空间
            if not namespace:
                namespace = HIKVISION_NAMESPACE
                
            # 构建查找路径
            search_path = f".//{{{namespace}}}{tag_name}"
            
            element = xml_root.find(search_path)
            if element is not None:
                return {k: v for k, v in element.attrib.items()}
            return {}
        except Exception as e:
            global_logger.warning(f"提取元素属性时出错: {str(e)}")
            return {}
    
    @staticmethod
    def extract_all_elements(xml_root: ET.Element, tag_name: str, namespace: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        提取所有指定标签的元素信息（支持标准命名空间）
        
        Args:
            xml_root: XML根元素
            tag_name: 标签名
            namespace: 命名空间（可选）
            
        Returns:
            元素信息列表
        """
        if not xml_root:
            return []
            
        try:
            # 如果没有指定命名空间，使用默认的Hikvision命名空间
            if not namespace:
                namespace = HIKVISION_NAMESPACE
                
            # 构建查找路径
            search_path = f".//{{{namespace}}}{tag_name}"
            
            elements = xml_root.findall(search_path)
            result = []
            
            for element in elements:
                element_info = {
                    'tag': element.tag,
                    'text': element.text.strip() if element.text else '',
                    'attributes': {k: v for k, v in element.attrib.items()}
                }
                result.append(element_info)
            
            return result
        except Exception as e:
            global_logger.warning(f"提取所有元素时出错: {str(e)}")
            return []
    
    @staticmethod
    def extract_nested_elements(xml_root: ET.Element, parent_tag: str, child_tag: str, 
                              namespace: Optional[str] = None) -> List[Dict[str, str]]:
        """
        提取嵌套元素结构（支持标准命名空间）
        
        Args:
            xml_root: XML根元素
            parent_tag: 父标签名
            child_tag: 子标签名
            namespace: 命名空间（可选）
            
        Returns:
            嵌套元素信息列表
        """
        if not xml_root:
            return []
            
        try:
            # 如果没有指定命名空间，使用默认的Hikvision命名空间
            if not namespace:
                namespace = HIKVISION_NAMESPACE
                
            # 构建查找路径
            parent_path = f".//{{{namespace}}}{parent_tag}"
            child_path = f".//{{{namespace}}}{child_tag}"
            
            parent_elements = xml_root.findall(parent_path)
            result = []
            
            for parent in parent_elements:
                # 查找子元素
                child_elements = parent.findall(child_path)
                for child in child_elements:
                    child_info = {
                        'tag': child.tag,
                        'text': child.text.strip() if child.text else '',
                        'attributes': {k: v for k, v in child.attrib.items()}
                    }
                    result.append(child_info)
            
            return result
        except Exception as e:
            global_logger.warning(f"提取嵌套元素时出错: {str(e)}")
            return []
    
    @staticmethod
    def extract_hikvision_element_text(xml_root: ET.Element, tag_name: str, default_value: str = "") -> str:
        """
        提取Hikvision标准命名空间的元素文本内容
        
        Args:
            xml_root: XML根元素
            tag_name: 标签名
            default_value: 默认值
            
        Returns:
            标签文本内容
        """
        return XmlProcessor.extract_element_text(xml_root, tag_name, HIKVISION_NAMESPACE, default_value)
    
    @staticmethod
    def extract_std_cgi_element_text(xml_root: ET.Element, tag_name: str, default_value: str = "") -> str:
        """
        提取Std-CGI标准命名空间的元素文本内容
        
        Args:
            xml_root: XML根元素
            tag_name: 标签名
            default_value: 默认值
            
        Returns:
            标签文本内容
        """
        return XmlProcessor.extract_element_text(xml_root, tag_name, STD_CGI_NAMESPACE, default_value)
    
    @staticmethod
    def format_xml_content(xml_content: str) -> str:
        """
        格式化XML内容（清理和标准化）
        
        Args:
            xml_content: 原始XML内容
            
        Returns:
            格式化后的XML内容
        """
        if not xml_content:
            return ""
            
        try:
            # 移除BOM
            if xml_content.startswith('\ufeff'):
                xml_content = xml_content[1:]
            
            # 清理空白字符
            xml_content = xml_content.strip()
            
            # 移除多余的空白行
            lines = xml_content.split('\n')
            formatted_lines = [line.strip() for line in lines if line.strip()]
            
            return '\n'.join(formatted_lines)
        except Exception as e:
            global_logger.warning(f"格式化XML内容时出错: {str(e)}")
            return xml_content

# 创建全局实例供其他模块使用
global_xml_processor = XmlProcessor()
