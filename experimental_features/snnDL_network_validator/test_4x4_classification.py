#!/usr/bin/env python3
"""
SnnDL 4x4分类网络验证测试

完整测试4x4分类网络的拓扑验证功能，展示网络拓扑验证器的所有能力
"""

import os
import sys
from datetime import datetime

# 添加项目路径
sys.path.append(os.path.dirname(__file__))

# 导入验证器
from __init__ import SnnDLNetworkTopologyValidator, validate_snnDL_network


def run_comprehensive_4x4_validation():
    """运行4x4分类网络的综合验证测试"""
    
    print("🚀 SnnDL 4x4分类网络拓扑验证测试")
    print("=" * 60)
    
    # 配置文件路径
    config_file = "/home/anarchy/SST/optimized_classification_package/scripts/test_classification_4x4.py"
    
    if not os.path.exists(config_file):
        print(f"❌ 配置文件不存在: {config_file}")
        return False
    
    # 创建验证器实例
    print("📋 初始化网络拓扑验证器...")
    validator = SnnDLNetworkTopologyValidator(config_file)
    
    try:
        # Step 1: 提取拓扑
        print("\n🔍 Step 1: 提取网络拓扑")
        print("-" * 40)
        topologies = validator.extract_topologies()
        
        print(f"✅ 拓扑提取完成:")
        for topo_name, topo_info in topologies.items():
            print(f"  {topo_name}: {len(topo_info.nodes)}节点, {sum(len(edges) for edges in topo_info.edges.values())}连接")
        
        # Step 2: 运行验证
        print("\n🛡️ Step 2: 执行网络验证")
        print("-" * 40)
        validation_results = validator.validate_all_layers()
        
        # 显示验证概览
        total_valid = sum(1 for result in validation_results.values() 
                         if isinstance(result, dict) and result.get('valid', False))
        total_tests = len([r for r in validation_results.values() if isinstance(r, dict)])
        
        print(f"📊 验证概览: {total_valid}/{total_tests} 层通过验证")
        
        for layer_name, result in validation_results.items():
            if isinstance(result, dict):
                status = "✅ 通过" if result.get('valid', False) else "❌ 失败"
                print(f"  {layer_name.upper()}层: {status}")
                
                # 显示关键指标
                if layer_name == 'physical':
                    print(f"    连通性: {'是' if result.get('connectivity') else '否'}")
                    print(f"    规律性: {'是' if result.get('regularity') else '否'}")
                    print(f"    对称性: {'是' if result.get('symmetry') else '否'}")
                elif layer_name == 'logical':
                    print(f"    前馈连接: {'正常' if result.get('feedforward_valid') else '异常'}")
                    print(f"    逻辑连接数: {result.get('total_logical_connections', 0)}")
                elif layer_name == 'data':
                    print(f"    前馈连接: {result.get('feedforward_connections', 0)}")
                    print(f"    反向连接: {result.get('backward_connections', 0)}")
                    print(f"    平均权重: {result.get('avg_connection_strength', 0):.4f}")
                elif layer_name == 'consistency':
                    print(f"    跨层一致性: {'是' if result.get('valid') else '否'}")
                
                # 显示错误
                if result.get('errors'):
                    print(f"    错误: {len(result['errors'])}个")
                    for error in result['errors'][:3]:
                        print(f"      - {error}")
                        
                # 显示警告
                if result.get('warnings'):
                    print(f"    警告: {len(result['warnings'])}个")
                    for warning in result['warnings'][:2]:
                        print(f"      - {warning}")
        
        # Step 3: 异常检测
        print("\n🚨 Step 3: 网络异常检测")
        print("-" * 40)
        anomalies = validator.detect_anomalies()
        
        if anomalies:
            print(f"检测到 {len(anomalies)} 个异常:")
            
            anomaly_types = {}
            for anomaly in anomalies:
                anomaly_type = anomaly.get('type', 'unknown')
                if anomaly_type not in anomaly_types:
                    anomaly_types[anomaly_type] = []
                anomaly_types[anomaly_type].append(anomaly)
            
            for anomaly_type, anomaly_list in anomaly_types.items():
                print(f"  📍 {anomaly_type}: {len(anomaly_list)}个")
                for anomaly in anomaly_list[:2]:  # 显示前2个
                    desc = anomaly.get('description', str(anomaly))
                    print(f"    - {desc}")
                if len(anomaly_list) > 2:
                    print(f"    - ... 还有{len(anomaly_list) - 2}个")
        else:
            print("✅ 未检测到异常")
        
        # Step 4: 性能分析
        print("\n⚡ Step 4: 网络性能分析") 
        print("-" * 40)
        performance = validator.analyze_performance()
        
        # 通信热点
        hotspots = performance.get('hotspots', [])
        if hotspots:
            print(f"🔥 通信热点 ({len(hotspots)}个):")
            for hotspot in hotspots[:3]:
                print(f"  PE{hotspot['node']}: {hotspot['connections']}连接, 权重{hotspot['total_weight']:.2f}")
        
        # 性能瓶颈
        bottlenecks = performance.get('bottlenecks', [])
        if bottlenecks:
            print(f"⚠️ 性能瓶颈 ({len(bottlenecks)}个):")
            for bottleneck in bottlenecks[:3]:
                print(f"  - {bottleneck['description']}")
        
        # 负载均衡
        load_analysis = performance.get('load_analysis', {})
        if load_analysis:
            balanced = "是" if load_analysis.get('balanced') else "否"
            print(f"⚖️ 负载均衡: {balanced}")
            print(f"  平均负载: {load_analysis.get('avg_load', 0):.2f}")
            print(f"  负载方差: {load_analysis.get('variance', 0):.2f}")
        
        if not hotspots and not bottlenecks:
            print("✅ 网络性能良好，无明显瓶颈")
        
        # Step 5: 生成验证报告
        print("\n📄 Step 5: 生成验证报告")
        print("-" * 40)
        
        report_file = f"snnDL_4x4_validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        report = validator.generate_report(report_file)
        
        print(f"📊 验证报告已生成: {report_file}")
        print(f"📏 报告长度: {len(report)} 字符")
        
        # 显示报告摘要
        lines = report.split('\n')
        summary_lines = [line for line in lines[:20] if line.strip()]  # 前20行非空行
        
        print("\n📋 报告摘要:")
        for line in summary_lines[:10]:  # 显示前10行
            if line.strip():
                print(f"  {line}")
        
        # 总体评估
        print("\n" + "=" * 60)
        
        overall_status = "优秀" if total_valid == total_tests and not anomalies else \
                        "良好" if total_valid >= total_tests * 0.75 and len(anomalies) < 3 else \
                        "需要改进"
        
        print(f"🎯 4x4分类网络总体评估: {overall_status}")
        print(f"📊 验证通过率: {total_valid}/{total_tests} ({total_valid/total_tests*100:.1f}%)")
        print(f"🚨 异常数量: {len(anomalies)}")
        print(f"⚡ 性能瓶颈: {len(bottlenecks)}")
        
        # 结论和建议
        if overall_status == "优秀":
            print("✅ 网络配置优秀，可以进行生产部署")
        elif overall_status == "良好":
            print("👍 网络配置良好，建议优化少量问题")
        else:
            print("⚠️ 网络配置需要改进，建议解决检测到的问题")
        
        return True
        
    except Exception as e:
        print(f"❌ 验证过程出现错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def demo_individual_features():
    """演示各个功能模块"""
    
    print("\n" + "=" * 60)
    print("🧪 功能模块演示")
    print("=" * 60)
    
    config_file = "/home/anarchy/SST/optimized_classification_package/scripts/test_classification_4x4.py"
    
    # 演示便捷函数
    print("\n1. 使用便捷函数进行快速验证:")
    print("-" * 40)
    
    try:
        result = validate_snnDL_network(config_file)
        
        print("✅ 便捷函数调用成功")
        print(f"  拓扑层数: {len(result['topologies'])}")
        print(f"  验证项目: {len(result['validation_results'])}")
        print(f"  报告长度: {len(result['report'])} 字符")
        
    except Exception as e:
        print(f"❌ 便捷函数调用失败: {e}")
    
    # 演示权重解析
    print("\n2. 权重解析器独立使用:")
    print("-" * 40)
    
    try:
        from parsers.weight_parser import parse_snnDL_weights
        
        weights_dir = "/home/anarchy/SST/optimized_classification_package/weights"
        weight_result = parse_snnDL_weights(weights_dir, threshold=0.01)
        
        print("✅ 权重解析成功")
        print(f"  权重矩阵: {len(weight_result['weight_matrices'])}个PE")
        print(f"  PE连接: {len(weight_result['pe_connections'])}个PE")
        print(f"  前馈连接: {len(weight_result['connection_patterns']['feedforward_connections'])}")
        print(f"  验证状态: {'通过' if weight_result['validation']['valid'] else '失败'}")
        
    except Exception as e:
        print(f"❌ 权重解析失败: {e}")
    
    print("\n✅ 功能演示完成")


def main():
    """主测试函数"""
    
    print("🌟 SnnDL网络拓扑验证器 - 4x4分类网络测试")
    print(f"⏰ 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("🎯 目标: 验证optimized_classification_package的4x4分类网络")
    
    # 运行综合验证测试
    success = run_comprehensive_4x4_validation()
    
    if success:
        # 演示个别功能
        demo_individual_features()
        
        print(f"\n🎉 测试完成! 网络拓扑验证器工作正常")
        print("💡 您可以使用此验证器来:")
        print("  - 验证任何SnnDL网络配置")
        print("  - 检测网络拓扑异常")
        print("  - 分析网络性能瓶颈") 
        print("  - 生成详细的验证报告")
        
    else:
        print(f"\n❌ 测试失败，请检查配置和环境")
    
    return success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)